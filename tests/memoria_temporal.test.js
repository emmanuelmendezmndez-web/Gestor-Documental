const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const crear = require('../app/static/memoria_temporal.js');

test('aplicación contextual es atómica y respeta prioridades', () => {
    const m = crear(); m.iniciar('consulta', 'documentos', {categoria:'Contratos', desde:'2025-03-01', hasta:'2025-03-31'});
    m.actualizar({categoria:'Actas'}); m.pendiente('duda_1');
    const previo = m.consultar();
    assert.throws(() => m.aplicarContexto({categoria:'Informes', desde:'2025-04-01'}, []));
    assert.deepEqual(m.consultar(), previo);
    assert.throws(() => m.aplicarContexto({categoria:'Informes', desde:'2025-04-01'}, ['categoria']));
    assert.deepEqual(m.consultar(), previo);
    m.aplicarContexto({categoria:'Informes', desde:'2025-04-01', hasta:'2025-04-30'}, ['categoria','desde','hasta']);
    assert.equal(m.consultar().filtros.categoria, 'Informes');
    const valido = m.consultar(); assert.throws(() => m.reemplazar('x'.repeat(201))); assert.deepEqual(m.consultar(), valido);
    m.limpiarFiltros(); assert.deepEqual(m.consultar(), {consulta:'consulta', intencion:'documentos', filtros:{}, manuales:[], pendientes:[], resueltas:[]});
});

test('mantiene consulta, intención y actualizaciones parciales sin perder los demás filtros', () => {
    const memoria = crear();
    memoria.iniciar('contratos de alumbrado', 'documentos', {categoria: 'Contratos', buscar: 'alumbrado'});
    memoria.actualizar({departamento: 'Tesorería', oficio: 'OF-1', autor: 'Autor', desde: '2026-01-01', hasta: '2026-12-31'});
    memoria.actualizar({departamento: 'Archivos'});
    assert.deepEqual(memoria.consultar().filtros, {categoria:'Contratos', buscar:'alumbrado', departamento:'Archivos', oficio:'OF-1', autor:'Autor', desde:'2026-01-01', hasta:'2026-12-31'});
    assert.equal(memoria.consultar().consulta, 'contratos de alumbrado');
    assert.equal(memoria.consultar().intencion, 'documentos');
});

test('las ediciones y eliminaciones manuales tienen prioridad sobre sugerencias', () => {
    const memoria = crear(); memoria.iniciar('prueba', 'documentos', {categoria:'Contratos', buscar:'obras'});
    memoria.actualizar({categoria:'Actas'}); memoria.quitar('buscar');
    memoria.actualizar({categoria:'Informes', buscar:'obras', departamento:'Tesorería'}, 'asistente');
    assert.deepEqual(memoria.consultar().filtros, {categoria:'Actas', departamento:'Tesorería'});
    memoria.pendiente('categoria_1'); memoria.resolver('categoria_1', 'elegir_informes', {categoria:'Informes'});
    assert.equal(memoria.consultar().filtros.categoria, 'Actas');
});

test('aclaraciones son identificadores acotados y sus cambios son atómicos', () => {
    const memoria = crear(); memoria.iniciar('expediente', 'expedientes');
    memoria.pendiente('fecha_1'); memoria.pendiente('fecha_1');
    assert.throws(() => memoria.resolver('fecha_1', 'opcion_1', {desde:'2026-03-01', hasta:'2026-02-01'}));
    assert.deepEqual(memoria.consultar().pendientes, ['fecha_1']);
    memoria.resolver('fecha_1', 'opcion_1', {desde:'2026-03-01', hasta:'2026-03-31'});
    assert.deepEqual(memoria.consultar().resueltas, [{id:'fecha_1', opcion:'opcion_1'}]);
    assert.throws(() => memoria.pendiente('contraseña o texto libre'));
    assert.throws(() => memoria.resolver('fecha_1', 'opcion_1'));
});

test('los estados devueltos son copias y los errores dejan intacto el último estado válido', () => {
    const memoria = crear(); const inicial = {categoria:'Contratos'};
    memoria.iniciar('consulta', 'documentos', inicial); inicial.categoria = 'alterada';
    const copia = memoria.consultar(); copia.filtros.categoria = 'cambio'; copia.manuales.push('autor');
    assert.equal(memoria.consultar().filtros.categoria, 'Contratos');
    const antes = memoria.obtenerUltimoValido();
    assert.throws(() => memoria.actualizar({password:'secreto'}));
    assert.throws(() => memoria.actualizar({desde:'2026-02-30'}));
    assert.deepEqual(memoria.consultar(), antes);
    assert.deepEqual(memoria.obtenerUltimoValido(), antes);
    antes.filtros.categoria = 'otra'; assert.equal(memoria.obtenerUltimoValido().filtros.categoria, 'Contratos');
});

test('cada cierre y el reinicio borran todo; las instancias son independientes', () => {
    for (const accion of ['cancelar', 'finalizar', 'reiniciar']) {
        const primera = crear(), segunda = crear();
        primera.iniciar('uno', 'documentos', {buscar:'privado'}); segunda.iniciar('dos', 'expedientes');
        primera.pendiente('duda_1'); primera.resolver('duda_1', 'opcion_1');
        primera[accion]();
        assert.equal(primera.consultar(), null); assert.equal(primera.obtenerUltimoValido(), null);
        assert.throws(() => primera.actualizar({buscar:'no activo'}));
        assert.equal(segunda.consultar().consulta, 'dos');
        primera.iniciar('nuevo'); assert.deepEqual(primera.consultar().resueltas, []);
    }
});

test('versión navegador no usa DOM, almacenamiento, red ni comparte instancias', () => {
    const contexto = {};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../app/static/memoria_temporal.js'), 'utf8'), contexto);
    const uno = contexto.crearMemoriaTemporal(), dos = contexto.crearMemoriaTemporal();
    uno.iniciar('uno'); dos.iniciar('dos'); uno.cancelar();
    assert.equal(uno.consultar(), null); assert.equal(dos.consultar().consulta, 'dos');
});
