import io
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from app.apertura_zip_acotada import LimiteZip, _LecturaAcotada, abrir_zip_acotado


class AperturaAcotadaTest(unittest.TestCase):
    def test_conteos_convencionales_mayor_menor_y_multidisco(self):
        self.crear(cantidad=2)
        original = self.zip.read_bytes()
        for campo, valor in ((8, 1), (10, 3), (4, 1), (6, 1)):
            data = bytearray(original)
            pos = data.rfind(b'PK\x05\x06')
            struct.pack_into('<H', data, pos + campo, valor)
            self.zip.write_bytes(data)
            with self.subTest(campo=campo), self.zip.open('rb') as f, self.assertRaises(zipfile.BadZipFile):
                with abrir_zip_acotado(f): pass
        # Ambos conteos concuerdan entre sí pero no con el directorio real.
        for valor in (1, 3):
            data = bytearray(original); pos = data.rfind(b'PK\x05\x06')
            struct.pack_into('<HH', data, pos + 8, valor, valor)
            self.zip.write_bytes(data)
            with self.zip.open('rb') as f, self.assertRaises(zipfile.BadZipFile):
                with abrir_zip_acotado(f): pass

    def test_zip64_marcadores_y_contradicciones(self):
        with patch.object(zipfile, 'ZIP64_LIMIT', 50): self.crear(cantidad=2, zip64=True)
        original = self.zip.read_bytes()
        pos = original.rfind(b'PK\x05\x06'); pos64 = original.rfind(b'PK\x06\x06')
        data = bytearray(original)
        struct.pack_into('<HHII', data, pos + 8, 65535, 65535, 0xffffffff, 0xffffffff)
        self.zip.write_bytes(data)
        with self.zip.open('rb') as f, abrir_zip_acotado(f) as z:
            self.assertEqual(len(z.filelist), 2)
        for offset, fmt, valor in ((pos + 10, '<H', 3), (pos64 + 24, '<Q', 1),
                                    (pos64 + 32, '<Q', 3), (pos64 + 16, '<I', 1)):
            alterado = bytearray(original)
            struct.pack_into(fmt, alterado, offset, valor)
            self.zip.write_bytes(alterado)
            with self.subTest(offset=offset), self.zip.open('rb') as f, self.assertRaises(zipfile.BadZipFile):
                with abrir_zip_acotado(f): pass

    def test_cierre_ambiguo(self):
        self.crear()
        data = bytearray(self.zip.read_bytes())
        pos = data.rfind(b'PK\x05\x06')
        falso = struct.pack('<4s4H2IH', b'PK\x05\x06', 0, 0, 0, 0, 0, 0, 0)
        struct.pack_into('<H', data, pos + 20, len(falso))
        self.zip.write_bytes(data + falso)
        with self.zip.open('rb') as f, self.assertRaises(zipfile.BadZipFile):
            with abrir_zip_acotado(f): pass

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='siged-prueba-apertura-zip-')
        self.addCleanup(self.tmp.cleanup)
        self.zip = Path(self.tmp.name) / 'ficticio.zip'

    def crear(self, cantidad=1, zip64=False):
        with zipfile.ZipFile(self.zip, 'w', allowZip64=True) as z:
            for i in range(cantidad):
                with z.open(f'storage/{i}.txt', 'w', force_zip64=zip64) as f:
                    f.write(b'datos ficticios')

    def test_valido_zip64_y_mismo_descriptor(self):
        with patch.object(zipfile, 'ZIP64_LIMIT', 50):
            self.crear(zip64=True)
        original = self.zip.read_bytes()
        self.assertIn(b'PK\x06\x06', original)
        with self.zip.open('rb') as archivo, abrir_zip_acotado(archivo) as z:
            self.assertEqual(z.read('storage/0.txt'), b'datos ficticios')
        self.assertEqual(self.zip.read_bytes(), original)

    def test_lectura_grande_rechazada_antes_del_read(self):
        class Fuente(io.BytesIO):
            def read(self, size=-1):
                raise AssertionError('No se debe intentar la lectura')
        lector = _LecturaAcotada(Fuente(b''), 10, 100, 20)
        with self.assertRaises(LimiteZip): lector.read(11)
        with self.assertRaises(LimiteZip): lector.read()

    def test_directorio_central_manipulado_no_asigna(self):
        self.crear()
        data = bytearray(self.zip.read_bytes())
        pos = data.rfind(b'PK\x05\x06')
        struct.pack_into('<I', data, pos + 12, 0x7fffffff)
        self.zip.write_bytes(data)
        with self.zip.open('rb') as f, self.assertRaises((LimiteZip, zipfile.BadZipFile, OSError)):
            with abrir_zip_acotado(f): pass

    def test_zip64_con_directorio_contradictorio(self):
        with patch.object(zipfile, 'ZIP64_LIMIT', 50):
            self.crear(zip64=True)
        data = bytearray(self.zip.read_bytes())
        pos = data.rfind(b'PK\x06\x06')
        self.assertGreaterEqual(pos, 0)
        struct.pack_into('<Q', data, pos + 40, 1 << 40)
        self.zip.write_bytes(data)
        with self.zip.open('rb') as f, self.assertRaises((LimiteZip, zipfile.BadZipFile)):
            with abrir_zip_acotado(f): pass

    def test_politica_existente_rechaza_ruta_no_permitida(self):
        with zipfile.ZipFile(self.zip, 'w') as z:
            z.writestr('../peligro', b'ficticio')
        with self.zip.open('rb') as f, self.assertRaises(ValueError):
            with abrir_zip_acotado(f): pass

    def test_limites_entradas_y_configuracion(self):
        self.crear(cantidad=2)
        with patch.dict(os.environ, {'GESTOR_RESPALDO_MAX_ENTRADAS': '1'}):
            with self.zip.open('rb') as f, self.assertRaises(LimiteZip):
                with abrir_zip_acotado(f): pass
        with patch.dict(os.environ, {'GESTOR_ZIP_MAX_LECTURA_BYTES': '0'}):
            with self.zip.open('rb') as f, self.assertRaises(ValueError):
                with abrir_zip_acotado(f): pass

    def test_truncado_y_presupuesto(self):
        self.crear()
        self.zip.write_bytes(self.zip.read_bytes()[:-10])
        with self.zip.open('rb') as f, self.assertRaises(zipfile.BadZipFile):
            with abrir_zip_acotado(f): pass
        self.crear()
        with patch.dict(os.environ, {'GESTOR_ZIP_MAX_LECTURA_TOTAL_BYTES': '1'}):
            with self.zip.open('rb') as f, self.assertRaises(LimiteZip):
                with abrir_zip_acotado(f): pass

    def test_tiempo_agotado_antes_de_lectura(self):
        fuente = io.BytesIO(b'ficticio')
        with patch('app.apertura_zip_acotada.time.monotonic', side_effect=[0, 2]):
            lector = _LecturaAcotada(fuente, 100, 100, 1)
            with self.assertRaises(LimiteZip): lector.read(1)
        self.assertEqual(fuente.tell(), 0)

    def test_cambio_durante_inspeccion(self):
        self.crear()
        with self.zip.open('rb') as f, self.assertRaises(LimiteZip):
            with abrir_zip_acotado(f):
                with self.zip.open('ab') as salida:
                    salida.write(b'x')
