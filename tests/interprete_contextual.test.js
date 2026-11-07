const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const interpretar = require('../app/static/interprete_contextual.js');
const ventana = {window:{}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../app/static/interprete_busqueda.js'), 'utf8'), ventana);
const detallar = (...args) => JSON.parse(JSON.stringify(ventana.window.sigedInterpretarBusqueda.detallar(...args)));
const contexto = () => ({estado:{filtros:{categoria:'Contratos', departamento:'Tesorería', desde:'2025-03-01', hasta:'2025-03-31'}, manuales:['categoria','departamento','desde','hasta'], pendientes:['duda_0']}, categorias:['Contratos','Informes','Actas'], areas:['Tesorería','Obras Públicas']});
const evaluar = (texto, ctx = contexto()) => interpretar(texto, ctx, detallar);

test('corrige mes con año inequívoco y acepta año explícito', () => {
    assert.deepEqual(evaluar('Mejor de abril').cambios, {desde:'2025-04-01', hasta:'2025-04-30'});
    assert.deepEqual(evaluar('Mejor de febrero de 2024').cambios, {desde:'2024-02-01', hasta:'2024-02-29'});
});
test('elimina o sustituye filtros manuales solo mediante orden explícita', () => {
    assert.deepEqual(evaluar('Quita Tesorería').cambios, {departamento:''});
    const resultado = evaluar('Mejor busca informes');
    assert.deepEqual(resultado.cambios, {categoria:'Informes'});
    assert.deepEqual(resultado.explicitos, ['categoria']);
    assert.deepEqual(evaluar('Conserva la categoría').conservar, ['categoria']);
    assert.deepEqual(evaluar('Quita fechas').cambios, {desde:'', hasta:''});
});
test('quitar Tesorería reconoce acentos y detecta cuando ya no está aplicada', () => {
    for (const orden of ['quitar tesoreria', 'quitar tesorería']) {
        const c = contexto(); c.estado.filtros.buscar = 'alumbrado';
        const antes = structuredClone(c);
        assert.deepEqual(evaluar(orden, c), {tipo:'cambios', cambios:{departamento:''}, explicitos:['departamento'], conservar:[]});
        assert.deepEqual(c, antes);
        delete c.estado.filtros.departamento;
        assert.deepEqual(evaluar(orden, c), {tipo:'aclaracion', motivo:'filtro_inexistente'});
    }
    const ambiguo = contexto(); ambiguo.estado.filtros.buscar = 'Tesorería';
    assert.equal(evaluar('quitar tesoreria', ambiguo).motivo, 'filtro_no_identificado');
    assert.equal(evaluar('quitar').tipo, 'aclaracion');
    assert.equal(evaluar('quitar finanzas').tipo, 'aclaracion');
});
test('las ambigüedades y contradicciones no proponen cambios', () => {
    for (const frase of ['Mejor de marzo y abril', 'Mejor busca contratos y actas', 'Quita Tesorería y conserva Tesorería', 'Quita Finanzas', 'Mejor de 03/04/2025']) {
        const r = evaluar(frase);
        assert.equal(r.tipo, 'aclaracion', frase);
        assert.equal(r.cambios, undefined, frase);
    }
    const c = contexto(); c.estado.filtros.hasta = '2026-01-01';
    assert.equal(evaluar('Mejor de abril', c).motivo, 'anio_ambiguo');
});
test('ausencia de contexto, limpieza, reinicio y consulta nueva', () => {
    assert.equal(evaluar('Mejor de abril', null).motivo, 'sin_contexto');
    assert.deepEqual(evaluar('Olvida los filtros'), {tipo:'limpiar_filtros'});
    assert.deepEqual(evaluar('Empieza de nuevo', null), {tipo:'reiniciar'});
    assert.deepEqual(evaluar('Informes de Tesorería'), {tipo:'consulta_nueva', consulta:'Informes de Tesorería'});
});
test('no modifica contexto, llama a red ni ejecuta búsquedas', () => {
    const c = contexto(), antes = structuredClone(c);
    const resultado = evaluar('Mejor de abril', c);
    assert.deepEqual(c, antes);
    assert.deepEqual(Object.keys(resultado).sort(), ['cambios','conservar','explicitos','tipo']);
});
