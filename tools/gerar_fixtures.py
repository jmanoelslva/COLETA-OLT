"""Copia as capturas reais (tools/capturas, fora do Git) para tests/fixtures
trocando seriais de ONU e nomes de clientes por valores fictícios."""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ORIGEM = RAIZ / "tools" / "capturas"
DESTINO = RAIZ / "tests" / "fixtures"

# nome da fixture → trecho do nome da captura (a mais recente vence)
MAPA = {
    "ont_info_todas.txt": "_show_ont_info_1_all.txt",
    "ont_info_online.txt": "_show_ont_info_1_1.txt",
    "ont_info_offline.txt": "_show_ont_info_1_4.txt",
    "optical_todas.txt": "_show_ont_optical_info_1_all.txt",
    "optical_uma.txt": "_show_ont_optical_info_1_1.txt",
    "optical_offline.txt": "_show_ont_optical_info_1_4.txt",
    "ddm_com_onus.txt": "_show_port_ddm_info_1_with_onu_optical.txt",
    "ddm_porta.txt": "_show_port_ddm_info_1.txt",
    "alarmes_ativos.txt": "_show_alarm_active_all.txt",
    "alarmes_historico.txt": "_show_alarm_history_all.txt",
    "firmware.txt": "_show_firmware_info.txt",
    "cpu.txt": "_show_cpu.txt",
    "fan.txt": "_show_fan.txt",
    "power.txt": "_show_power_state.txt",
    "memoria.txt": "_show_memory.txt",
    "temperatura.txt": "_show_temperature.txt",
    "versao.txt": "_show_version.txt",
    "uptime.txt": "_show_uptime.txt",
    "time.txt": "_show_time.txt",
}

MAPA.update({
    "datacom_onus_porta.txt": "_show_interface_gpon_1_1_1_onu.txt",
    "datacom_onus_porta2.txt": "_show_interface_gpon_1_1_2_onu.txt",
    "datacom_onu_online.txt": "_show_interface_gpon_1_1_1_onu_2.txt",
    "datacom_onu_offline.txt": "_show_interface_gpon_1_1_1_onu_91.txt",
    "datacom_rssi.txt": "_show_interface_gpon_1_1_1_onu_2_rssi.txt",
    "datacom_rssi_offline.txt": "_show_interface_gpon_1_1_1_onu_91_rssi.txt",
    "datacom_alarmes.txt": "_show_alarm.txt",
    "datacom_cpu.txt": "_show_system_cpu.txt",
    "datacom_memoria.txt": "_show_system_memory.txt",
    "datacom_ambiente.txt": "_show_environment.txt",
    "datacom_plataforma.txt": "_show_platform.txt",
    "datacom_transceivers.txt": "_show_interface_transceivers.txt",
    "datacom_firmware.txt": "_show_firmware.txt",
    "datacom_uptime.txt": "_show_system_uptime.txt",
    "datacom_contagem.txt": "_show_onu_global_count.txt",
    "datacom_erro_sintaxe.txt": "_show_interface_gpon_1_1_1_onu_rssi.txt",
    "datacom_portas_gpon.txt": "_show_interface_gpon.txt",
})

seriais: dict[str, str] = {}
nomes: dict[str, str] = {}


def _serial(m: re.Match) -> str:
    sn = m.group(0)
    if sn not in seriais:
        seriais[sn] = f"TEST{len(seriais) + 1:08X}"
    return seriais[sn]


def anonimizar(texto: str) -> str:
    # Serial de ONU: 12 caracteres alfanuméricos com ao menos um dígito, como coluna ou "SN : ...".
    texto = re.sub(r"(?<=\s)(?=[A-Z0-9]*\d)[A-Z0-9]{12}(?=\s)", _serial, texto)

    def _nome(m: re.Match) -> str:
        n = m.group(2)
        if n not in nomes:
            nomes[n] = f"CLIENTE-{len(nomes) + 1:03d}"
        return m.group(1) + nomes[n]

    texto = re.sub(r"^([ \t]*(?:Description|Name)[ \t]*:[ \t]*)(\S.*?)[ \t]*$", _nome, texto, flags=re.M)
    # Datacom: nome do cliente na última coluna da lista de ONUs.
    return re.sub(r"^(\d+/\d+/\d+[ \t].*?(?:N/A|-?\d+\.\d+)[ \t]+(?:N/A|-?\d+\.\d+)[ \t]+)(\S.*?)([ \t]*)$",
                  lambda m: _nome(m) + m.group(3), texto, flags=re.M)


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    arquivos = sorted(ORIGEM.glob("*.txt"))
    for destino, trecho in MAPA.items():
        candidatos = [a for a in arquivos if a.name.endswith(trecho)]
        if not candidatos:
            print(f"faltando: {trecho}")
            continue
        (DESTINO / destino).write_text(anonimizar(candidatos[-1].read_text(encoding="utf-8")), encoding="utf-8")
        print(f"ok: {destino}")


if __name__ == "__main__":
    main()
