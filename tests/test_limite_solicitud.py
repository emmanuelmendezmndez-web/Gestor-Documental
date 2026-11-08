"""Ejecuta las pruebas de subida exclusivamente con datos temporales aislados."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class LimiteSolicitudAisladoTest(unittest.TestCase):
    def test_integracion(self):
        raiz = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='siged-limite-') as carpeta:
            entorno = os.environ.copy()
            entorno.update(GESTOR_DATA_DIR=carpeta, GESTOR_SECRET_KEY='clave-ficticia-limite',
                           GESTOR_MAX_CUERPO_BYTES=str(21 * 1024 * 1024),
                           PYTHONPATH=os.pathsep.join((str(raiz / 'tests'), str(raiz))))
            subprocess.run([sys.executable, str(raiz / 'tests' / 'limite_solicitud_casos.py')],
                           cwd=raiz, env=entorno, check=True, timeout=180)


if __name__ == '__main__':
    unittest.main()
