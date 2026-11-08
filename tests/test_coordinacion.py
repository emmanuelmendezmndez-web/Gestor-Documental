"""Coordinación entre procesos usando únicamente un directorio ficticio."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CoordinacionTest(unittest.TestCase):
    def test_selector_rechaza_servidor_activo(self):
        self.mantener(False)
        resultado = self.ejecutar('from app.coordinacion import seleccionar_originales; seleccionar_originales()')
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn('bloqueo de SIGED', resultado.stderr)

    def test_diagnostico_exclusivo(self):
        servidor = self.mantener(False)
        r = self.ejecutar('from app.coordinacion import diagnosticar_restauracion; diagnosticar_restauracion()')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('bloqueo de SIGED', r.stderr)
        servidor.stdin.write('\n'); servidor.stdin.flush(); servidor.wait(timeout=15)
        proceso = self.proceso("import app.diagnostico_restauracion as d; "
                               "from app.coordinacion import diagnosticar_restauracion; "
                               "d._inspeccionar=lambda: (print('listo', flush=True), input()); diagnosticar_restauracion()")
        self.addCleanup(self.detener, proceso)
        self.assertEqual(proceso.stdout.readline().strip(), 'listo')
        otro = self.ejecutar('from app.coordinacion import diagnosticar_restauracion; diagnosticar_restauracion()')
        self.assertNotEqual(otro.returncode, 0)
        self.assertIn('bloqueo de SIGED', otro.stderr)
        proceso.stdin.write('\n'); proceso.stdin.flush(); proceso.wait(timeout=15)
        self.assertEqual(self.ejecutar('from app.coordinacion import diagnosticar_restauracion; diagnosticar_restauracion()').returncode, 0)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="siged-prueba-coordinacion-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = os.environ.copy()
        self.env["GESTOR_DATA_DIR"] = str(self.root)
        self.env.pop("GESTOR_SECRET_KEY", None)
        self.env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        self.env["PYTHONUNBUFFERED"] = "1"
        python_real = Path(sys.base_prefix) / "python.exe"
        self.python = str(python_real) if os.name == "nt" and python_real.is_file() else sys.executable
        if self.python != sys.executable:
            self.env["PYTHONPATH"] = os.pathsep.join((str(Path(sys.prefix) / "Lib" / "site-packages"), self.env["PYTHONPATH"]))

    def proceso(self, codigo):
        return subprocess.Popen([self.python, "-c", codigo], env=self.env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def mantener(self, exclusivo):
        proceso = self.proceso("from app.coordinacion import BloqueoDatos; "
                               f"b=BloqueoDatos(exclusivo={exclusivo}); "
                               "print('listo', flush=True); input(); b.cerrar()")
        self.addCleanup(self.detener, proceso)
        linea = proceso.stdout.readline()
        self.assertEqual(linea.strip(), "listo", proceso.stderr.read() if proceso.poll() is not None else linea)
        return proceso

    @staticmethod
    def detener(proceso):
        if proceso.poll() is None:
            proceso.terminate()
        proceso.communicate(timeout=15)

    def ejecutar(self, codigo):
        return subprocess.run([sys.executable, "-c", codigo], env=self.env, capture_output=True,
                              text=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def test_compartidos_y_exclusivo(self):
        primero = self.mantener(False)
        segundo = self.mantener(False)
        resultado = self.ejecutar("from app.respaldo import restaurar_respaldo; from pathlib import Path; restaurar_respaldo(Path('falso.zip'))")
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("bloqueo de SIGED", resultado.stderr)
        self.assertEqual({p.name for p in self.root.iterdir()}, {".siged-coordinacion.lock"})
        primero.stdin.write("\n"); primero.stdin.flush(); primero.wait(timeout=15)
        segundo.stdin.write("\n"); segundo.stdin.flush(); segundo.wait(timeout=15)
        exclusivo = self.mantener(True)
        self.assertIsNone(exclusivo.poll())

    def test_arranque_bloqueado_y_dos_restauradores(self):
        activo = self.mantener(True)
        segundo = self.ejecutar("from app.coordinacion import BloqueoDatos; BloqueoDatos(exclusivo=True)")
        self.assertNotEqual(segundo.returncode, 0)
        for modulo in ("app.crear_usuario", "app.database", "app.eliminaciones"):
            r = subprocess.run([sys.executable, "-m", modulo], env=self.env, capture_output=True,
                               text=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertNotEqual(r.returncode, 0, modulo)
            self.assertIn("bloqueo de SIGED", r.stderr)
        copia = self.ejecutar("from app.respaldo import crear_respaldo; crear_respaldo()")
        self.assertNotEqual(copia.returncode, 0)
        self.assertIn("bloqueo de SIGED", copia.stderr)
        inicio = self.ejecutar("import app.main")
        self.assertNotEqual(inicio.returncode, 0)
        self.assertIn("bloqueo de SIGED", inicio.stderr)
        uvicorn = subprocess.run([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "0"],
                                 env=self.env, capture_output=True, text=True, timeout=30,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertNotEqual(uvicorn.returncode, 0)
        self.assertIn("bloqueo de SIGED", uvicorn.stderr)
        self.assertEqual({p.name for p in self.root.iterdir()}, {".siged-coordinacion.lock"})
        activo.terminate(); activo.wait(timeout=15)
        inicio = self.ejecutar("import app.main; print('iniciado')")
        self.assertEqual(inicio.returncode, 0, inicio.stderr)
        self.assertIn("iniciado", inicio.stdout)

    def test_servidor_real_impide_restauracion(self):
        servidor = self.proceso("import app.main; print('listo', flush=True); input()")
        self.addCleanup(self.detener, servidor)
        self.assertEqual(servidor.stdout.readline().strip(), "listo")
        otro = self.proceso("import app.main; print('listo', flush=True); input()")
        self.addCleanup(self.detener, otro)
        self.assertEqual(otro.stdout.readline().strip(), "listo")
        r = self.ejecutar("from app.respaldo import restaurar_respaldo; from pathlib import Path; restaurar_respaldo(Path('falso.zip'))")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("bloqueo de SIGED", r.stderr)

    def test_error_de_acceso_falla_sin_tocar_datos(self):
        ruta = self.root / ".siged-coordinacion.lock"
        ruta.mkdir()
        marca = self.root / "datos-ficticios.txt"
        marca.write_bytes(b"intacto")
        r = self.ejecutar("import app.main")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("bloqueo de SIGED", r.stderr)
        self.assertEqual(marca.read_bytes(), b"intacto")
        self.assertFalse((self.root / ".secret_key").exists())
        self.assertFalse((self.root / "gestor.db").exists())


if __name__ == "__main__":
    unittest.main()
