"""Intercalaciones controladas con conexiones SQLite y archivos ficticios."""

from contextlib import contextmanager
import os
from pathlib import Path
import threading

from fastapi import HTTPException
from starlette.requests import Request

from app.configuracion import DATA_DIR, DB_PATH, STORAGE_DIR
from app.database import conectar, inicializar_db
from app.seguridad import NoAutenticado, hashear_password, requiere_permiso
import app.operaciones_documentales as operaciones
import app.rutas_documentos as documentos
import app.rutas_expedientes as expedientes
import app.rutas_papelera as papelera

assert DATA_DIR == Path(os.environ['GESTOR_DATA_DIR']).resolve()
assert DATA_DIR.name.startswith('siged-prueba-concurrencia-') and DB_PATH.parent == DATA_DIR
inicializar_db()
STORAGE_DIR.mkdir(exist_ok=True)
with conectar() as db:
    usuarios = [db.execute('INSERT INTO usuarios(usuario,nombre,password_hash,rol,departamento) VALUES(?,?,?,?,?)',
                (nombre,nombre,hashear_password('ClavePrueba123!'),rol,'Tesorería')).lastrowid
                for nombre,rol in [('editoruno','editor'),('editordos','editor'),('adminprueba','admin')]]
    expediente = db.execute("INSERT INTO expedientes(titulo,folio) VALUES('Expediente global','EXP-PRUEBA')").lastrowid


def peticion(indice, permiso):
    r = Request({'type':'http','method':'POST','path':'/prueba','headers':[], 'client':('127.0.0.1',1),
                 'server':('127.0.0.1',8000),'scheme':'http','query_string':b'',
                 'session':{'usuario_id':usuarios[indice],'version':0}})
    requiere_permiso(permiso)(r)
    return r


def crear(nombre, papelera=False):
    archivo = STORAGE_DIR / (nombre + '.txt')
    archivo.write_bytes(b'contenido ficticio')
    with conectar() as db:
        ident = db.execute('INSERT INTO documentos(titulo,nombre_archivo,nombre_guardado,categoria,tamano_bytes,departamento,eliminado_en) VALUES(?,?,?,?,?,?,?)',
            (nombre,archivo.name,archivo.name,'Otros',len(b'contenido ficticio'),'Tesorería','2026-01-01' if papelera else None)).lastrowid
    return ident, archivo


def fila(ident):
    with conectar() as db:
        datos = db.execute('SELECT id,titulo,departamento,version,eliminado_en,eliminado_por FROM documentos WHERE id=?',(ident,)).fetchone()
        return dict(datos) if datos else None


def auditoria(ident, accion):
    with conectar() as db:
        return db.execute('SELECT COUNT(*) FROM actividad WHERE entidad_id=? AND accion=? AND resultado=?',(ident,accion,'exito')).fetchone()[0]


def editar(r, ident, titulo, area='Tesorería'):
    return documentos.editar_documento(r,ident,titulo,'Otros','','',area,'','',1)


def intercalar(primera, segunda):
    tomada = threading.Event()
    continuar = threading.Event()
    resultados = {}

    class Conexion:
        def __init__(self, db): self.db = db
        def execute(self, sql, *args):
            respuesta = self.db.execute(sql, *args)
            if threading.current_thread().name == 'primera' and sql == 'BEGIN IMMEDIATE':
                tomada.set()
                if not continuar.wait(20): raise TimeoutError('No se liberó la transacción')
            return respuesta
        def __getattr__(self, nombre): return getattr(self.db,nombre)

    @contextmanager
    def controlada():
        with conectar() as db:
            yield Conexion(db)

    def ejecutar(clave, funcion):
        try:
            respuesta = funcion()
            resultados[clave] = ('respuesta', respuesta.status_code, respuesta.headers.get('location', ''))
        except HTTPException as exc:
            resultados[clave] = ('http', exc.status_code)
        except NoAutenticado:
            resultados[clave] = ('no_autenticado',)
        except Exception as exc:
            resultados[clave] = ('error', type(exc).__name__, str(exc))

    from unittest.mock import patch
    with patch.object(operaciones, 'conectar', controlada):
        a = threading.Thread(target=ejecutar,args=('a',primera),name='primera')
        b = threading.Thread(target=ejecutar,args=('b',segunda),name='segunda')
        a.start()
        assert tomada.wait(20), resultados
        b.start()
        b.join(.3)
        assert b.is_alive(), 'La segunda escritura no esperó el bloqueo SQLite'
        continuar.set()
        a.join(30); b.join(30)
        assert not a.is_alive() and not b.is_alive(), resultados
    return resultados


# Dos versiones iguales: una se confirma y la otra informa conflicto.
i,p = crear('dos_ediciones')
a,b = peticion(0,'editar'),peticion(1,'editar')
r = intercalar(lambda:editar(a,i,'Primera'),lambda:editar(b,i,'Segunda'))
assert 'editado' in r['a'][2] and 'conflicto_edicion' in r['b'][2] and fila(i)['titulo']=='Primera'
assert auditoria(i,'editar') == 1

# Papelera gana frente a edición: ya no es posible editar el documento.
i,p = crear('editar_papelera')
a,b = peticion(1,'papelera'),peticion(0,'editar')
r = intercalar(lambda:documentos.eliminar_documento(a,i),lambda:editar(b,i,'No debe guardarse'))
assert 'eliminado' in r['a'][2] and r['b']==('http',404) and fila(i)['titulo']=='editar_papelera'
assert auditoria(i,'editar') == 0

# Dos restauraciones y purga frente a restauración nunca anuncian dos éxitos.
i,p = crear('restaurar_doble',True)
a,b = peticion(0,'restaurar'),peticion(1,'restaurar')
r = intercalar(lambda:papelera.restaurar_documento(a,i),lambda:papelera.restaurar_documento(b,i))
assert 'restaurado' in r['a'][2] and r['b']==('http',404) and auditoria(i,'restaurar')==1

i,p = crear('purga_restaurar',True)
a,b = peticion(2,'eliminar'),peticion(0,'restaurar')
r = intercalar(lambda:papelera.eliminar_definitivamente(a,i),lambda:papelera.restaurar_documento(b,i))
assert 'eliminado_definitivo' in r['a'][2] and r['b']==('http',404) and fila(i) is None and not p.exists()
assert auditoria(i,'restaurar') == 0

# Cambio de área del documento frente a edición anterior.
i,p = crear('cambio_area')
a,b = peticion(2,'editar'),peticion(0,'editar')
r = intercalar(lambda:editar(a,i,'Movido','Recursos Humanos'),lambda:editar(b,i,'Edición anterior'))
assert 'editado' in r['a'][2] and r['b']==('http',404) and fila(i)['departamento']=='Recursos Humanos'

# Una revocación simultánea espera al cierre de la escritura ya autorizada.
from fastapi.responses import RedirectResponse
i,p = crear('revocacion_simultanea'); r = peticion(0,'editar')
def revocar_en_paralelo():
    with conectar() as db:
        db.execute("UPDATE usuarios SET rol='lector' WHERE id=?", (usuarios[0],))
    return RedirectResponse('/ok', status_code=303)
resultado = intercalar(lambda:editar(r,i,'Edición confirmada'), revocar_en_paralelo)
assert 'editado' in resultado['a'][2] and resultado['b'][1]==303 and fila(i)['titulo']=='Edición confirmada'
with conectar() as db:
    db.execute("UPDATE usuarios SET rol='editor' WHERE id=?", (usuarios[0],))

# La selección completa se confirma o se rechaza sin cambios parciales.
i,p = crear('masivo_1'); j,q = crear('masivo_2')
a,b = peticion(0,'papelera'),peticion(1,'papelera')
r = intercalar(lambda:documentos.enviar_documentos_papelera(a,[i,j]),lambda:documentos.eliminar_documento(b,j))
assert 'documentos_papelera' in r['a'][2] and r['b']==('http',404)
assert fila(i)['eliminado_por']==usuarios[0] and fila(j)['eliminado_por']==usuarios[0]
assert auditoria(i,'papelera_enviar')==auditoria(j,'papelera_enviar')==1

i,p = crear('seleccion_valida'); j,q = crear('seleccion_cambiada')
documentos.eliminar_documento(peticion(1,'papelera'),j)
try:
    documentos.enviar_documentos_papelera(peticion(0,'papelera'),[i,j])
    raise AssertionError('Se aceptó la selección modificada')
except HTTPException as exc:
    assert exc.status_code==404 and fila(i)['eliminado_en'] is None and auditoria(i,'papelera_enviar')==0

# La restauración y la purga masivas también rechazan toda selección obsoleta.
i,p = crear('restauracion_masiva_1',True); j,q = crear('restauracion_masiva_2',True)
papelera.restaurar_documento(peticion(1,'restaurar'),j)
try:
    papelera.restaurar_documentos_masivo(peticion(0,'restaurar'),[i,j])
    raise AssertionError('Se aceptó una restauración parcialmente modificada')
except HTTPException as exc:
    assert exc.status_code==404 and fila(i)['eliminado_en'] is not None and auditoria(i,'restaurar')==0
try:
    papelera.eliminar_documentos_seleccionados(peticion(2,'eliminar'),[i,j])
    raise AssertionError('Se aceptó una purga parcialmente modificada')
except HTTPException as exc:
    assert exc.status_code==404 and fila(i) is not None and p.exists()

# Vinculación global, pero solo de documentos accesibles; duplicados son conflicto.
i,p = crear('vincular'); a,b = peticion(0,'gestionar_expedientes'),peticion(1,'gestionar_expedientes')
r = intercalar(lambda:expedientes.vincular_documentos_masivo(a,expediente,[i]),lambda:expedientes.vincular_documentos_masivo(b,expediente,[i]))
assert 'documentos_vinculados' in r['a'][2] and r['b']==('http',409) and auditoria(i,'expediente_vincular')==1
j,q = crear('vinculo_no_parcial')
try:
    expedientes.vincular_documentos_masivo(peticion(0,'gestionar_expedientes'),expediente,[i,j])
    raise AssertionError('Se aceptó una selección parcialmente vinculada')
except HTTPException as exc:
    with conectar() as db:
        assert exc.status_code==409 and not db.execute('SELECT 1 FROM expediente_documentos WHERE documento_id=?',(j,)).fetchone()

# Revalidar revocación, desactivación, versión de sesión y área después del permiso inicial.
for cambio in ('rol','activo','sesion','area'):
    i,p = crear('revocacion_'+cambio)
    r = peticion(0,'editar')
    with conectar() as db:
        columna, valor = {'rol':('rol','lector'),'activo':('activo',0),'sesion':('version_sesion',1),'area':('departamento','Recursos Humanos')}[cambio]
        db.execute(f'UPDATE usuarios SET {columna}=? WHERE id=?',(valor,usuarios[0]))
    try:
        editar(r,i,'No autorizado')
        raise AssertionError('La autorización anterior continuó vigente: '+cambio)
    except HTTPException as exc:
        assert (cambio=='rol' and exc.status_code==403) or (cambio=='area' and exc.status_code==404)
    except NoAutenticado:
        assert cambio in {'activo','sesion'}
    assert fila(i)['titulo']=='revocacion_'+cambio and auditoria(i,'editar')==0
    with conectar() as db:
        db.execute("UPDATE usuarios SET rol='editor',activo=1,version_sesion=0,departamento='Tesorería' WHERE id=?",(usuarios[0],))

# La misma revalidación protege envíos masivos y purgas tras revocar el acceso.
i,p = crear('revocacion_masiva'); j,q = crear('revocacion_masiva_2')
r = peticion(0,'papelera')
with conectar() as db:
    db.execute("UPDATE usuarios SET rol='lector' WHERE id=?", (usuarios[0],))
try:
    documentos.enviar_documentos_papelera(r,[i,j])
    raise AssertionError('Se aceptó un envío masivo tras revocar el rol')
except HTTPException as exc:
    assert exc.status_code==403 and fila(i)['eliminado_en'] is None and fila(j)['eliminado_en'] is None
with conectar() as db:
    db.execute("UPDATE usuarios SET rol='editor' WHERE id=?", (usuarios[0],))

i,p = crear('purga_desactivado',True); r = peticion(2,'eliminar')
with conectar() as db:
    db.execute('UPDATE usuarios SET activo=0 WHERE id=?', (usuarios[2],))
try:
    papelera.eliminar_definitivamente(r,i)
    raise AssertionError('Se aceptó una purga con usuario desactivado')
except NoAutenticado:
    assert fila(i) is not None and p.exists() and auditoria(i,'eliminar_definitivo')==0
with conectar() as db:
    db.execute('UPDATE usuarios SET activo=1 WHERE id=?', (usuarios[2],))

# Contención simulada con espera corta exclusivamente en esta base ficticia.
from unittest.mock import patch
@contextmanager
def conexion_corta():
    with conectar() as db:
        db.execute('PRAGMA busy_timeout=100')
        yield db
i,p = crear('bloqueo',True); r = peticion(0,'restaurar')
with conectar() as bloqueo:
    bloqueo.execute('BEGIN IMMEDIATE')
    with patch.object(operaciones,'conectar',conexion_corta):
        try:
            papelera.restaurar_documento(r,i)
            raise AssertionError('No se detectó el bloqueo')
        except HTTPException as exc:
            assert exc.status_code==503
assert fila(i)['eliminado_en'] is not None and auditoria(i,'restaurar')==0
print('OK: concurrencia documental, autorización vigente, selecciones, expedientes y bloqueos')
