const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const consultar = require('../app/static/catalogo_ayuda_clippy.js');
const general = 'Consulta con una persona administradora para obtener orientación sobre esta función.';
const contexto = (pantalla, capacidades) => ({pantalla, capacidades});

test('lector consulta expedientes sin instrucciones de gestión', () => {
    const c = contexto('expedientes', {ver:true, ver_expedientes:true, gestionar_expedientes:false});
    assert.match(consultar('expedientes', c), /consultar/);
    assert.equal(consultar('gestionar_expedientes', c), general);
    assert.equal(consultar('vincular_documentos', contexto('expediente', c.capacidades)), general);
});
test('editor restaura pero no recibe instrucciones de eliminación definitiva', () => {
    const c = contexto('papelera', {ver:true, papelera:true, restaurar:true, eliminar:false});
    assert.match(consultar('restaurar', c), /Restaurar selección/);
    assert.equal(consultar('eliminar_definitivamente', c), general);
});
test('administrador con capacidades explícitas recibe ayudas de los temas disponibles', () => {
    const c = {ver:true, ver_expedientes:true, gestionar_expedientes:true, subir:true, papelera:true, restaurar:true, eliminar:true, usuarios:true};
    for (const [tema, pantalla] of [['biblioteca','biblioteca'], ['busqueda','buscar'], ['subida','subir'], ['expedientes','expedientes'], ['gestionar_expedientes','expedientes'], ['vincular_documentos','expediente'], ['papelera','papelera'], ['restaurar','papelera'], ['eliminar_definitivamente','papelera'], ['usuarios','usuarios']]) {
        assert.notEqual(consultar(tema, contexto(pantalla, c)), general, tema);
    }
});
test('pantalla desconocida, permisos ausentes, falsos o inconsistentes usan orientación segura', () => {
    for (const c of [null, {}, contexto('desconocida', {usuarios:true}), contexto('usuarios', {}), contexto('usuarios', {usuarios:false}), contexto('usuarios', {usuarios:'true'}), contexto('usuarios', Object.create({usuarios:true}))]) assert.equal(consultar('usuarios', c), general);
    assert.equal(consultar('gestionar_expedientes', contexto('expedientes', {ver:true, gestionar_expedientes:true, ver_expedientes:false})), general);
    assert.equal(consultar('restaurar', contexto('papelera', {ver:true, restaurar:true, papelera:false})), general);
    assert.equal(consultar('subida', contexto('subir', {rol:'admin', subir:true})), general);
    assert.equal(consultar('respaldos', contexto('inicio', {usuarios:true})), general);
});
test('permisos ofrece orientación general sin prometer acceso', () => {
    assert.match(consultar('permisos', contexto('inicio', {ver:true})), /dependen de tu cuenta/);
    assert.equal(consultar('permisos', contexto('inicio', {})), general);
});
test('el catálogo no ejecuta acciones ni incorpora datos del contexto', () => {
    const c = contexto('biblioteca', {ver:true}); c.documento = 'dato personal confidencial';
    const copia = structuredClone(c);
    assert.doesNotMatch(consultar('biblioteca', c), /dato personal confidencial/);
    assert.deepEqual(c, copia);
    const aislado = {};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../app/static/catalogo_ayuda_clippy.js'), 'utf8'), aislado);
    assert.equal(aislado.sigedConsultarAyuda('biblioteca', c), consultar('biblioteca', c));
});
