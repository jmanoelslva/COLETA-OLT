"""`python -m coletor` — sobe API + agendador (um processo só: o agendador vive nele)."""

import logging
import os

import uvicorn


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("COLETOR_LOG", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("paramiko").setLevel(logging.WARNING)
    uvicorn.run(
        "coletor.api:app",
        host=os.environ.get("COLETOR_HOST", "127.0.0.1"),
        port=int(os.environ.get("COLETOR_PORTA", "8090")),
        workers=1,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
