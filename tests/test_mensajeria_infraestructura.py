"""Ejecuta los casos de infraestructura con datos aislados y en otro proceso."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class InfraestructuraMensajeriaAisladaTest(unittest.TestCase):
    def test_infraestructura(self):
        self._ejecutar("mensajeria_infraestructura_casos.py")

    def test_reconciliacion(self):
        self._ejecutar("mensajeria_reconciliacion_casos.py")

    def _ejecutar(self, casos):
        raiz = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="siged-prueba-mensajeria-") as temporal:
            env = os.environ.copy()
            env.update(
                GESTOR_DATA_DIR=temporal,
                GESTOR_MENSAJERIA_DIR=str(Path(temporal) / ".siged-mensajeria"),
                GESTOR_SECRET_KEY="clave-ficticia-exclusiva-prueba-mensajeria",
                PYTHONPATH=str(raiz),
            )
            subprocess.run(
                [sys.executable, str(raiz / "tests" / casos)],
                env=env, cwd=raiz, check=True, timeout=300,
            )
