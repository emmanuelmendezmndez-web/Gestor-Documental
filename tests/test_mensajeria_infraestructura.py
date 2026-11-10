"""Ejecuta los casos de infraestructura con datos aislados y en otro proceso."""

import os
import subprocess
import sys
import sysconfig
import tempfile
import unittest
from pathlib import Path


class InfraestructuraMensajeriaAisladaTest(unittest.TestCase):
    def test_infraestructura(self):
        self._ejecutar("mensajeria_infraestructura_casos.py")

    def test_reconciliacion(self):
        self._ejecutar("mensajeria_reconciliacion_casos.py")

    def test_motor(self):
        self._ejecutar("mensajeria_motor_casos.py")

    def test_adjuntos(self):
        self._ejecutar("mensajeria_adjuntos_casos.py", plazo=1200)

    def _ejecutar(self, casos, *seleccion, plazo=600):
        raiz = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="siged-prueba-mensajeria-") as temporal:
            env = os.environ.copy()
            # Windows: el lanzador del venv puede dejar el intérprete vivo
            # al recibir terminate(). Se conserva el site-packages del venv.
            ejecutable = sys._base_executable if os.name == "nt" else sys.executable
            env.pop("__PYVENV_LAUNCHER__", None)
            env.update(
                GESTOR_DATA_DIR=temporal,
                GESTOR_MENSAJERIA_DIR=str(Path(temporal) / ".siged-mensajeria"),
                GESTOR_SECRET_KEY="clave-ficticia-exclusiva-prueba-mensajeria",
                PYTHONPATH=os.pathsep.join((str(raiz), sysconfig.get_path("purelib"))),
            )
            subprocess.run(
                [ejecutable, str(raiz / "tests" / casos), *seleccion],
                env=env, cwd=raiz, check=True, timeout=plazo,
            )
