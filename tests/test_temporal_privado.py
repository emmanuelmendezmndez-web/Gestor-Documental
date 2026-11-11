import errno
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.diagnostico_io import detalle_error
from app.temporal_privado import directorio_privado, verificar_acl_privada


class TemporalPrivadoTest(unittest.TestCase):
    def test_timeout_acl_conserva_operacion_y_codigo_sin_comando_privado(self):
        with (patch('app.temporal_privado._volumen_acl'),
              patch('app.temporal_privado.subprocess.run',
                    side_effect=subprocess.TimeoutExpired('ruta privada', 6)),
              self.assertRaises(OSError) as fallo):
            verificar_acl_privada(Path('privado'), 6)
        self.assertEqual(fallo.exception.errno, errno.ETIMEDOUT)
        detalle = detalle_error(fallo.exception)
        self.assertIn('TimeoutExpired', detalle)
        self.assertIn('timeout=6', detalle)
        self.assertNotIn('ruta privada', detalle)

    def test_acl_herencia_y_limpieza(self):
        with tempfile.TemporaryDirectory() as parent:
            with directorio_privado(parent) as p:
                (p / 'dato').write_bytes(b'ficticio')
                self.assertTrue(p.is_dir())
            self.assertFalse(p.exists())

    def test_rechazo_volumen(self):
        with tempfile.TemporaryDirectory() as parent:
            with (patch('app.temporal_privado._volumen_acl', side_effect=OSError),
                  self.assertRaises(OSError), directorio_privado(parent)):
                self.fail('No debe copiar')
            self.assertEqual(list(Path(parent).iterdir()), [])

    def test_rechazo_acl_y_limpieza(self):
        with tempfile.TemporaryDirectory() as parent:
            with patch('app.temporal_privado.subprocess.run') as run:
                run.return_value.returncode = 1
                with self.assertRaises(OSError), directorio_privado(parent):
                    self.fail('No debe copiar')
            self.assertEqual(list(Path(parent).iterdir()), [])
