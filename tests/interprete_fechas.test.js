const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function motor(fechaActual = '2026-01-01T12:00:00') {
    class Fecha extends Date { constructor(...args) { super(...(args.length ? args : [fechaActual])); } }
    const ctx = {window:{}, Date:Fecha};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'app', 'static', 'interprete_busqueda.js'), 'utf8'), ctx);
    return texto => JSON.parse(JSON.stringify(ctx.window.sigedInterpretarBusqueda.detallar(texto,
        ['Contratos','Actas','Informes','Certificados','Bitacoras','Inventarios','Otros'],
        ['Tesorería','Obras Públicas','Recursos Humanos','Archivos'])));
}

test('fechas relativas usan días locales y cruzan años', () => {
    const evaluar = motor();
    for (const [frase, desde, hasta] of [
        ['hoy','2026-01-01','2026-01-01'], ['ayer','2025-12-31','2025-12-31'],
        ['esta semana','2025-12-29','2026-01-04'], ['semana pasada','2025-12-22','2025-12-28'],
        ['este mes','2026-01-01','2026-01-31'], ['mes pasado','2025-12-01','2025-12-31'],
        ['este año','2026-01-01','2026-12-31'], ['año pasado','2025-01-01','2025-12-31'],
    ]) assert.deepEqual(evaluar(frase).filtros, {desde,hasta}, frase);
});

test('rangos y fechas completas inequívocas', () => {
    const evaluar = motor();
    for (const [frase, desde, hasta] of [
        ['de enero a marzo de 2026','2026-01-01','2026-03-31'],
        ['entre el 1 de marzo y el 30 de abril de 2026','2026-03-01','2026-04-30'],
        ['febrero de 2024','2024-02-01','2024-02-29'], ['2026-04-30','2026-04-30','2026-04-30'],
        ['diciembre del año pasado','2025-12-01','2025-12-31'],
        ['30/04/2026','2026-04-30','2026-04-30'], ['30 de abril de 2026','2026-04-30','2026-04-30'],
    ]) assert.deepEqual(evaluar(frase).filtros, {desde,hasta}, frase);
});

test('consultas compuestas, oficios y folios', () => {
    const evaluar = motor();
    assert.deepEqual(evaluar('Necesito informes de Tesorería de enero a marzo de 2026').filtros,
        {departamento:'Tesorería',categoria:'Informes',desde:'2026-01-01',hasta:'2026-03-31'});
    assert.deepEqual(evaluar('oficio OF-123/2026').filtros, {oficio:'of-123/2026'});
    assert.deepEqual(evaluar('OF-123/2026').filtros, {oficio:'of-123/2026'});
    assert.deepEqual(evaluar('OF. no. RH-54/2025 hoy').filtros, {oficio:'rh-54/2025',desde:'2026-01-01',hasta:'2026-01-01'});
    assert.equal(evaluar('busca el expediente EXP-2025-000123').expediente, 'exp-2025-000123');
    assert.deepEqual(evaluar('busca el expediente EXP-2025-000123').filtros, {});
    assert.equal(evaluar('actas de RRHH').filtros.departamento, 'Recursos Humanos');
});

test('ambigüedad y contradicción producen aviso sin filtro temporal', () => {
    const evaluar = motor();
    for (const frase of ['marzo', 'de enero a marzo', 'entre el 1 de marzo y el 30 de abril',
        '03/04/2026', '2026-02-30', 'hoy ayer', 'de noviembre a marzo de 2026']) {
        const resultado = evaluar(frase);
        assert.ok(resultado.avisos.length, frase);
        assert.equal(resultado.filtros.desde, undefined, frase);
        assert.equal(resultado.filtros.hasta, undefined, frase);
    }
    const varias = evaluar('contratos y actas');
    assert.equal(varias.filtros.categoria, undefined);
    assert.ok(varias.avisos.length);
    assert.equal(evaluar('contrato de obras de alumbrado').filtros.departamento, undefined);
    assert.deepEqual(evaluar('').filtros, {});
    assert.deepEqual(evaluar('%%%').filtros, {buscar:'%%%'});
});
