"""Agendador: uma sessão SSH e uma fila por OLT.

A CLI das OLTs executa um comando por vez mesmo com várias sessões abertas
(confirmado na C-DATA FD1616GS: um `show time` espera 20–50 s atrás de um
`ddm-info ... with-onu-optical` de outra sessão). Por isso cada OLT tem uma
sessão só, com prioridade:

1. pedidos manuais (Coletar agora, Ler ONU agora);
2. alarmes; 3. equipamento; 4. ONUs;
5. ONUs que acabaram de cair/voltar (detalhe com a hora exata — Datacom);
6. sinal na OLT, em pedaços pequenos (C-DATA: uma porta, ~1 min; Datacom:
   uma ONU, ~3 s). Entre um pedaço e outro, o mais prioritário passa na frente.

Um ciclo nunca é empilhado sobre outro: o próximo só começa quando o atual
termina. Intervalos são lidos do banco a cada volta (mudar pela API vale na hora).
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Callable

from . import coletas
from .cdata.parsers import ErroCli
from .cdata.sessao import ErroSessao
from .config import OltConfig, Settings
from .db import Banco, agora_utc, de_iso, iso
from .drivers import DRIVERS, Driver

log = logging.getLogger(__name__)

OCIOSO_KEEPALIVE_S = 120

Rotina = Callable[..., dict]

# Tipos de coleta que existem para qualquer fabricante (nomes usados na API/telas).
TIPOS = ("alarmes", "sistema", "onus", "rx_olt")
PRIORIDADE_URGENTE = 2.5
PRIORIDADE_RX = 3


@dataclass
class Pedido:
    tipo: str
    funcao: Rotina
    kwargs: dict
    futuro: Future


class ColetorOlt(threading.Thread):
    def __init__(self, olt: OltConfig, banco: Banco, settings: Settings, estado: coletas.EstadoOlt):
        super().__init__(name=olt.id, daemon=True)
        self.olt = olt
        self.driver: Driver = DRIVERS[olt.fabricante]
        self.banco = banco
        self.estado = estado
        self.sessao = self.driver.sessao(olt, settings.known_hosts)
        self.fila: queue.Queue[Pedido | None] = queue.Queue()
        self.ultima: dict[str, float] = {}
        self.rx_pendentes: list[dict] = []
        self.em_execucao: dict | None = None
        self.parar = threading.Event()
        self._carregar_ultimas()

    def _carregar_ultimas(self) -> None:
        """Depois de reiniciar o serviço, não refaz na hora o que acabou de rodar."""
        with self.banco.conexao() as c:
            for t in self.driver.tipos:
                r = c.execute(
                    "SELECT MAX(inicio) AS i FROM coletas WHERE olt_id = ? AND tipo = ? AND ok = 1 AND origem = 'agendada'",
                    (self.olt.id, t),
                ).fetchone()
                if r and r["i"]:
                    atraso = (agora_utc() - de_iso(r["i"])).total_seconds()
                    self.ultima[t] = time.monotonic() - max(atraso, 0)

    # ------------------------------------------------------------ pedidos

    def acordar(self) -> None:
        self.fila.put(None)

    def pedir(self, tipo: str, funcao: Rotina, **kwargs) -> Future:
        f: Future = Future()
        self.fila.put(Pedido(tipo, funcao, kwargs, f))
        return f

    def reiniciar_ciclo_rx(self, portas: list[int] | None = None) -> int:
        """Coleta manual do sinal na OLT: entra na fila em pedaços, sem travar
        os alarmes. Com `portas`, só essas vão para a frente do ciclo atual."""
        itens = self.driver.itens_rx(self.olt, self.banco, self.estado, portas)
        if portas:
            self.rx_pendentes = itens + [i for i in self.rx_pendentes if i not in itens]
        else:
            self.rx_pendentes = itens
            self.ultima["rx_olt"] = time.monotonic()
        self.acordar()
        return len(itens)

    # ------------------------------------------------------------ laço

    def _urgentes(self) -> list[dict]:
        return self.estado.extras.setdefault("urgentes", [])

    def _vencimentos(self) -> dict[str, float]:
        par = self.banco.parametros()
        venc = {t: self.ultima.get(t, 0.0) + float(par[self.driver.tipos[t][1]]) for t in self.driver.tipos}
        venc["rx_olt"] = self.ultima.get("rx_olt", 0.0) + float(par["intervalo_rx_olt_s"])
        return venc

    def _prioridade(self, tipo: str) -> float:
        if tipo == "rx_olt":
            return PRIORIDADE_RX
        if tipo == "urgente":
            return PRIORIDADE_URGENTE
        return self.driver.tipos[tipo][0]

    def _proxima_agendada(self) -> tuple[str | None, float]:
        """→ (tipo a rodar agora ou None, segundos até a próxima)."""
        agora = time.monotonic()
        venc = self._vencimentos()
        if self.rx_pendentes:
            venc["rx_olt"] = agora  # ciclo em andamento: próximo pedaço
        if self._urgentes():
            venc["urgente"] = agora
        vencidos = sorted((self._prioridade(t), t) for t, v in venc.items() if v <= agora)
        if vencidos:
            return vencidos[0][1], 0.0
        return None, min(venc.values()) - agora

    def run(self) -> None:
        while not self.parar.is_set():
            try:
                pedido = self.fila.get_nowait()
            except queue.Empty:
                pedido = None
            if pedido is not None:
                self._atender(pedido)
                continue

            tipo, espera = self._proxima_agendada()
            if tipo is None:
                try:
                    pedido = self.fila.get(timeout=min(max(espera, 0.5), 30.0))
                except queue.Empty:
                    self._manter_viva()
                    continue
                if pedido is not None:
                    self._atender(pedido)
                continue

            if tipo == "urgente":
                self._rodar_seguro("onu", self.driver.consultar_onu, self._urgentes().pop(0), "agendada")
            elif tipo == "rx_olt":
                if not self.rx_pendentes:
                    self.rx_pendentes = self.driver.itens_rx(self.olt, self.banco, self.estado)
                    self.ultima["rx_olt"] = time.monotonic()
                    if not self.rx_pendentes:
                        continue
                self._rodar_seguro("rx_olt", self.driver.funcao_rx, self.rx_pendentes.pop(0), "agendada")
            else:
                self.ultima[tipo] = time.monotonic()
                self._rodar_seguro(tipo, self.driver.tipos[tipo][2], {}, "agendada")
        self.sessao.fechar()

    def _manter_viva(self) -> None:
        if self.sessao.conectada and time.monotonic() - self.sessao.ultimo_uso > OCIOSO_KEEPALIVE_S:
            try:
                self.sessao.manter_viva()
            except Exception as e:  # noqa: BLE001
                log.info("[%s] keepalive falhou, reconecta na próxima: %s", self.name, e)
                self.sessao.fechar()

    def _atender(self, p: Pedido) -> None:
        if not p.futuro.set_running_or_notify_cancel():
            return
        try:
            p.futuro.set_result(self._rodar(p.tipo, p.funcao, p.kwargs, "manual"))
        except Exception as e:  # noqa: BLE001
            p.futuro.set_exception(e)

    def _rodar_seguro(self, tipo: str, funcao: Rotina, kwargs: dict, origem: str) -> None:
        try:
            self._rodar(tipo, funcao, kwargs, origem)
        except Exception:  # noqa: BLE001 — já registrado; o laço não pode morrer
            pass

    def _rodar(self, tipo: str, funcao: Rotina, kwargs: dict, origem: str) -> dict:
        inicio = agora_utc()
        self.em_execucao = {"tipo": tipo, "inicio": iso(inicio), "origem": origem, "args": kwargs}
        # Pedaços do rodízio de ONU (Datacom) são muitos: só falhas vão para o log de coletas.
        registrar = not (tipo in ("rx_olt", "onu") and "onu_id" in kwargs and origem == "agendada")
        cid = None
        if registrar:
            with self.banco.conexao() as c:
                cid = c.execute(
                    "INSERT INTO coletas (olt_id, tipo, origem, inicio, detalhe) VALUES (?,?,?,?,?)",
                    (self.olt.id, tipo, origem, iso(inicio), json.dumps({"args": kwargs})),
                ).lastrowid
        ok, erro, resultado = False, None, {}
        try:
            resultado = funcao(self.sessao, self.olt, self.banco, self.estado, **kwargs)
            ok = True
            return resultado
        except ErroSessao as e:
            erro = f"sessão: {e}"
            self.sessao.fechar()
            raise
        except ErroCli as e:
            erro = f"OLT respondeu: {e}"
            raise
        except Exception as e:
            erro = f"{type(e).__name__}: {e}"
            log.exception("[%s] %s falhou", self.name, tipo)
            self.sessao.fechar()
            raise
        finally:
            self.em_execucao = None
            with self.banco.conexao() as c:
                if cid is not None:
                    c.execute("UPDATE coletas SET fim = ?, ok = ?, erro = ?, detalhe = ? WHERE id = ?",
                              (iso(agora_utc()), int(ok), erro,
                               json.dumps({"args": kwargs, **resultado}, default=str), cid))
                elif not ok:
                    c.execute("INSERT INTO coletas (olt_id, tipo, origem, inicio, fim, ok, erro, detalhe) "
                              "VALUES (?,?,?,?,?,0,?,?)",
                              (self.olt.id, tipo, origem, iso(inicio), iso(agora_utc()), erro,
                               json.dumps({"args": kwargs})))
                elif tipo == "rx_olt":
                    # Marca de "última leitura de sinal na OLT" sem um registro por ONU.
                    c.execute("DELETE FROM coletas WHERE olt_id = ? AND tipo = 'rx_olt' AND origem = 'rodizio'",
                              (self.olt.id,))
                    c.execute("INSERT INTO coletas (olt_id, tipo, origem, inicio, fim, ok, detalhe) "
                              "VALUES (?, 'rx_olt', 'rodizio', ?, ?, 1, ?)",
                              (self.olt.id, iso(inicio), iso(agora_utc()), json.dumps({"args": kwargs})))
            if registrar or not ok:
                nivel = logging.INFO if ok else logging.WARNING
                log.log(nivel, "[%s] %s%s %s em %ss%s", self.name, tipo, f" {kwargs}" if kwargs else "",
                        "ok" if ok else "FALHOU", int((agora_utc() - inicio).total_seconds()),
                        f": {erro}" if erro else "")

    def status(self) -> dict:
        agora = time.monotonic()
        prox = {t: max(0, int(v - agora)) for t, v in self._vencimentos().items()}
        return {"faixa": "unica", "conectada": self.sessao.conectada, "em_execucao": self.em_execucao,
                "proxima_em_s": prox, "fila": self.fila.qsize(), "rx_olt_pendentes": len(self.rx_pendentes),
                "urgentes": len(self._urgentes())}


class Agendador:
    def __init__(self, olts: list[OltConfig], banco: Banco, settings: Settings):
        self.banco = banco
        self.settings = settings
        self.estados: dict[str, coletas.EstadoOlt] = {}
        self.coletores: dict[str, ColetorOlt] = {}
        self._olts_iniciais = olts
        self._limpeza = threading.Thread(target=self._loop_limpeza, name="limpeza", daemon=True)
        self._parar = threading.Event()
        self._lock = threading.Lock()

    def iniciar(self) -> None:
        for o in self._olts_iniciais:
            self.aplicar(o.id, o)
        self._limpeza.start()

    def aplicar(self, olt_id: str, olt: OltConfig | None) -> None:
        """(Re)inicia o coletor de uma OLT após cadastro/edição; None = excluída.
        O coletor antigo termina o comando em andamento e fecha a sessão."""
        from .inventario import FABRICANTES

        with self._lock:
            antigo = self.coletores.pop(olt_id, None)
            if antigo:
                antigo.parar.set()
                antigo.acordar()
            if (olt is None or not olt.ativa or olt.fabricante not in DRIVERS
                    or not FABRICANTES.get(olt.fabricante, {}).get("coleta")):
                return
            estado = self.estados.setdefault(olt_id, coletas.EstadoOlt())
            novo = ColetorOlt(olt, self.banco, self.settings, estado)
            self.coletores[olt_id] = novo
            novo.start()

    def parar(self) -> None:
        self._parar.set()
        for c in self.coletores.values():
            c.parar.set()
            c.acordar()

    def acordar_todas(self) -> None:
        for c in self.coletores.values():
            c.acordar()

    def _coletor(self, olt_id: str) -> ColetorOlt:
        if olt_id not in self.coletores:
            raise KeyError(f"coleta pausada para {olt_id}")
        return self.coletores[olt_id]

    def forcar(self, olt_id: str, tipo: str, **kwargs) -> Future:
        c = self._coletor(olt_id)
        if tipo == "rx_olt":
            n = c.reiniciar_ciclo_rx(kwargs.get("portas"))
            f: Future = Future()
            f.set_result({"enfileirado": True, "pedacos": n,
                          "aviso": "Entrou na fila em pedaços; os valores aparecem conforme cada um termina."})
            return f
        return c.pedir(tipo, c.driver.tipos[tipo][2], **kwargs)

    def consultar_onu(self, olt_id: str, porta: int, onu_id: int) -> Future:
        c = self._coletor(olt_id)
        return c.pedir("onu", c.driver.consultar_onu, porta=porta, onu_id=onu_id)

    def status(self, olt_id: str) -> list[dict]:
        c = self.coletores.get(olt_id)
        return [c.status()] if c else []

    def _loop_limpeza(self) -> None:
        while not self._parar.wait(60):
            try:
                dias = int(self.banco.parametros()["retencao_dias"])
                apagados = self.banco.limpar_antigos(dias)
                if any(apagados.values()):
                    log.info("limpeza (%s dias): %s", dias, apagados)
            except Exception:  # noqa: BLE001
                log.exception("limpeza falhou")
            self._parar.wait(6 * 3600)
