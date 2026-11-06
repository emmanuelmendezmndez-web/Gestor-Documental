// Ejecuta los archivos reales en un DOM simulado, en el mismo orden del navegador.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function iniciar() {
    const controles = {};
    for (const id of ['busqueda-asistida', 'abrir-busqueda-asistida', 'cerrar-busqueda-asistida',
        'busqueda-global', 'consulta-asistida-texto', 'editar-consulta-asistida', 'filtros-sugeridos', 'form-busqueda-asistida']) {
        controles[id] = { value: '', hidden: true, listeners: {}, addEventListener(tipo, fn) { this.listeners[tipo] = fn; } };
    }
    const dialogo = controles['busqueda-asistida'];
    dialogo.querySelector = () => null;
    dialogo.querySelectorAll = () => [];
    dialogo.showModal = () => { dialogo.open = true; };
    dialogo.close = () => { dialogo.open = false; };
    controles['busqueda-global'].focus = () => { controles['busqueda-global'].enfocado = true; };
    controles['editar-consulta-asistida'].focus = () => {};
    let destino;
    const window = {
        sigedOpcionesBusqueda: { categorias: ['Contratos', 'Actas', 'Informes', 'Certificados', 'Bitacoras', 'Inventarios', 'Otros'],
            areas: ['Tesorería', 'Obras Públicas', 'Recursos Humanos'], areaUsuario: 'Tesorería', rol: 'lector', usuarioId: 10 },
        location: { pathname: '/inicio', assign: valor => { destino = valor; } },
    };
    class Fecha extends Date {
        constructor(...args) { super(...(args.length ? args : ['2026-10-28T12:00:00'])); }
    }
    const contexto = { window, Date: Fecha, URLSearchParams, URL, console,
        sessionStorage: { getItem: () => '1', setItem() {} },
        fetch: async () => ({ ok: true, json: async () => ({}) }),
        document: { getElementById: id => controles[id], querySelector: () => null, addEventListener() {} },
    };
    for (const nombre of ['interprete_busqueda.js', 'busqueda_asistida.js']) {
        const archivo = path.join(__dirname, '..', 'app', 'static', nombre);
        vm.runInNewContext(fs.readFileSync(archivo, 'utf8'), contexto);
    }
    return { interpretar: texto => JSON.parse(JSON.stringify(window.sigedInterpretarBusqueda(
        texto, window.sigedOpcionesBusqueda.categorias, window.sigedOpcionesBusqueda.areas))), controles, destino: () => destino };
}

test('reglas actuales de interpretación, incluidas ambigüedades', () => {
    const { interpretar } = iniciar();
    const casos = [
        ['', {}], ['documento', { buscar: 'documento' }],
        ['Contratos de Obras Públicas de marzo de 2025', { departamento: 'Obras Públicas', categoria: 'Contratos', desde: '2025-03-01', hasta: '2025-03-31' }],
        ['ACTAS de Tesorería', { departamento: 'Tesorería', categoria: 'Actas' }],
        ['oficio OF-123/2026', { oficio: 'of-123/2026', desde: '2026-01-01', hasta: '2026-12-31' }],
        ['informe alumbrado año pasado', { categoria: 'Informes', desde: '2025-01-01', hasta: '2025-12-31', buscar: 'alumbrado' }],
        ['contratos marzo', { categoria: 'Contratos', desde: '2026-03-01', hasta: '2026-03-31' }],
        ['bitácoras reparación', { categoria: 'Bitacoras', buscar: 'reparacion' }],
        ['contrato $% luz_azul', { categoria: 'Contratos', buscar: 'luz azul' }],
        ['de enero a marzo', { desde: '2026-01-01', hasta: '2026-01-31', buscar: 'a marzo' }],
    ];
    for (const [entrada, esperado] of casos) assert.deepEqual(interpretar(entrada), esperado, entrada);
});

test('el envío asistido utiliza los filtros propuestos y rechaza una frase vacía', () => {
    const prueba = iniciar();
    const form = prueba.controles['form-busqueda-asistida'];
    form.listeners.submit({ preventDefault() {} });
    assert.equal(prueba.destino(), undefined);
    prueba.controles['busqueda-global'].value = 'contratos marzo';
    prueba.controles['abrir-busqueda-asistida'].listeners.click();
    form.listeners.submit({ preventDefault() {} });
    const params = new URLSearchParams(prueba.destino().slice(2));
    assert.equal(params.get('categoria'), 'Contratos');
    assert.equal(params.get('desde'), '2026-03-01');
    assert.equal(params.get('hasta'), '2026-03-31');
});

test('el diálogo usa la consulta compartida y permite editarla o cancelarla', () => {
    const prueba = iniciar();
    const controles = prueba.controles;
    controles['busqueda-global'].value = 'contratos marzo';
    controles['abrir-busqueda-asistida'].listeners.click();
    assert.equal(controles['busqueda-asistida'].open, true);
    assert.equal(controles['consulta-asistida-texto'].textContent, 'contratos marzo');
    controles['cerrar-busqueda-asistida'].listeners.click();
    assert.equal(controles['busqueda-asistida'].open, false);
    assert.equal(controles['busqueda-global'].value, 'contratos marzo');
    assert.equal(prueba.destino(), undefined);
    controles['busqueda-global'].value = '';
    controles['abrir-busqueda-asistida'].listeners.click();
    assert.equal(controles['consulta-asistida-texto'].textContent, 'Sin consulta escrita');
    controles['editar-consulta-asistida'].listeners.click();
    assert.equal(controles['busqueda-asistida'].open, false);
    assert.equal(controles['busqueda-global'].enfocado, true);
});

test('el intérprete separado coincide con las reglas anteriores y funciona sin DOM', () => {
    const categorias = ['Contratos', 'Actas', 'Informes', 'Certificados', 'Bitacoras', 'Inventarios', 'Otros'];
    const areas = ['Tesorería', 'Obras Públicas', 'Recursos Humanos'];
    class Fecha extends Date {
        constructor(...args) { super(...(args.length ? args : ['2026-10-28T12:00:00'])); }
    }
    const anterior = { module: { exports: {} }, Date: Fecha };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'fixtures', 'interprete_anterior.js'), 'utf8'), anterior);
    const viejo = anterior.module.exports(categorias, areas);
    const actual = { window: {}, Date: Fecha };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'app', 'static', 'interprete_busqueda.js'), 'utf8'), actual);
    const consultas = ['', '   ', 'documento', '%%%_@', 'OFICIO OF-123/2026', 'of. no. 22/2024',
        'contratos de Obras Públicas marzo 2025', 'contrato de alumbrado del año pasado',
        'bitácoras y ACTAS', 'certificados Tesorería', 'inventarios recursos humanos',
        'informe febrero 2024', 'informe febrero 2023', 'diciembre este año', 'marzo',
        'de enero a marzo', '2024 2025', 'oficios sin número', 'archivo documentos',
        'café-público / foo_bar', 'x'.repeat(250), 'TESORERIA', 'Oficio 123/2026 marzo',
        'enero y obras públicas', 'contratos inventarios', 'oficio número A-1'];
    for (const consulta of consultas) {
        const esperado = JSON.parse(JSON.stringify(viejo(consulta)));
        const obtenido = JSON.parse(JSON.stringify(actual.window.sigedInterpretarBusqueda(consulta, categorias, areas)));
        assert.deepEqual(obtenido, esperado, consulta);
    }
});
