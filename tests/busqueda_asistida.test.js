// Ejecuta el archivo real en un DOM simulado. La exposición solo existe en memoria.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function iniciar() {
    const controles = {};
    for (const id of ['busqueda-asistida', 'abrir-busqueda-asistida', 'cerrar-busqueda-asistida',
        'frase-busqueda-asistida', 'filtros-sugeridos', 'form-busqueda-asistida']) {
        controles[id] = { value: '', hidden: true, listeners: {}, addEventListener(tipo, fn) { this.listeners[tipo] = fn; } };
    }
    const dialogo = controles['busqueda-asistida'];
    dialogo.querySelector = () => null;
    dialogo.querySelectorAll = () => [];
    dialogo.showModal = () => {};
    dialogo.close = () => {};
    controles['frase-busqueda-asistida'].focus = () => {};
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
    const archivo = path.join(__dirname, '..', 'app', 'static', 'busqueda_asistida.js');
    const fuente = fs.readFileSync(archivo, 'utf8');
    const marca = '    function actualizar() {';
    assert.equal(fuente.split(marca).length, 2, 'Cambió el punto de instrumentación de la prueba');
    vm.runInNewContext(fuente.replace(marca, '    window.interpretarPrueba = interpretar;\n' + marca), contexto);
    return { interpretar: texto => JSON.parse(JSON.stringify(window.interpretarPrueba(texto))), controles, destino: () => destino };
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
    prueba.controles['frase-busqueda-asistida'].value = 'contratos marzo';
    form.listeners.submit({ preventDefault() {} });
    const params = new URLSearchParams(prueba.destino().slice(2));
    assert.equal(params.get('categoria'), 'Contratos');
    assert.equal(params.get('desde'), '2026-03-01');
    assert.equal(params.get('hasta'), '2026-03-31');
});
