// Ejecuta los archivos reales en un DOM simulado, en el mismo orden del navegador.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function iniciar() {
    const controles = {};
    for (const id of ['busqueda-asistida', 'abrir-busqueda-asistida', 'cerrar-busqueda-asistida',
        'busqueda-global', 'consulta-asistida-texto', 'editar-consulta-asistida', 'filtros-sugeridos', 'form-busqueda-asistida',
        'filtros-reconocidos', 'filtros-adicionales', 'agregar-filtros', 'sin-filtros-reconocidos', 'filtros-adicionales-activos',
        ...['buscar', 'categoria', 'departamento', 'oficio', 'autor', 'desde', 'hasta'].map(clave => `asistido-${clave}`)]) {
        controles[id] = { value: '', hidden: true, listeners: {}, addEventListener(tipo, fn) { this.listeners[tipo] = fn; }, append(...items) { this.agregados = items; } };
    }
    const dialogo = controles['busqueda-asistida'];
    dialogo.querySelector = () => null;
    dialogo.querySelectorAll = () => [];
    dialogo.showModal = () => { dialogo.open = true; };
    dialogo.close = () => { dialogo.open = false; };
    controles['busqueda-global'].focus = () => { controles['busqueda-global'].enfocado = true; };
    controles['editar-consulta-asistida'].focus = () => {};
    controles['asistido-desde'].focus = () => {};
    controles['form-busqueda-asistida'].reportValidity = () => true;
    controles['form-busqueda-asistida'].checkValidity = () => true;
    for (const id of ['filtros-reconocidos', 'filtros-adicionales']) {
        controles[id].children = [];
        Object.defineProperty(controles[id], 'childElementCount', {get() { return this.children.length; }});
        controles[id].appendChild = function (grupo) {
            if (grupo.parentElement) grupo.parentElement.children = grupo.parentElement.children.filter(item => item !== grupo);
            this.children.push(grupo); grupo.parentElement = this;
        };
    }
    for (const clave of ['buscar', 'categoria', 'departamento', 'oficio', 'autor', 'desde', 'hasta']) {
        const grupo = {}; controles[`asistido-${clave}`].closest = () => grupo;
        controles['filtros-adicionales'].appendChild(grupo);
    }
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
        document: { getElementById: id => controles[id], querySelector: () => null, addEventListener() {}, createElement: () => ({}) },
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
        ['oficio OF-123/2026', { oficio: 'of-123/2026' }],
        ['informe alumbrado año pasado', { categoria: 'Informes', desde: '2025-01-01', hasta: '2025-12-31', buscar: 'alumbrado' }],
        ['contratos marzo', { categoria: 'Contratos' }],
        ['bitácoras reparación', { categoria: 'Bitacoras', buscar: 'reparacion' }],
        ['contrato $% luz_azul', { categoria: 'Contratos', buscar: 'luz azul' }],
        ['de enero a marzo', {}],
    ];
    for (const [entrada, esperado] of casos) assert.deepEqual(interpretar(entrada), esperado, entrada);
});

test('el envío asistido utiliza los filtros propuestos y rechaza una frase vacía', () => {
    const prueba = iniciar();
    const form = prueba.controles['form-busqueda-asistida'];
    form.listeners.submit({ preventDefault() {} });
    assert.equal(prueba.destino(), undefined);
    prueba.controles['busqueda-global'].value = 'contratos marzo de 2026';
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

test('se aplican los valores editados y se omiten los filtros eliminados', () => {
    const prueba = iniciar(); const c = prueba.controles;
    c['busqueda-global'].value = 'contratos de Tesorería marzo 2025';
    c['abrir-busqueda-asistida'].listeners.click();
    assert.equal(c['asistido-categoria'].value, 'Contratos');
    assert.equal(c['asistido-departamento'].value, 'Tesorería');
    for (const [campo, valor] of Object.entries({categoria:'Informes', departamento:'Recursos Humanos', desde:'2025-02-01', hasta:'2025-03-02', oficio:'OF-4', autor:'Autor ficticio', buscar:''})) {
        c[`asistido-${campo}`].value = valor;
        c[`asistido-${campo}`].listeners.input();
    }
    c['form-busqueda-asistida'].listeners.submit({preventDefault() {}});
    const params = new URLSearchParams(prueba.destino().slice(2));
    assert.deepEqual(Object.fromEntries(params), {categoria:'Informes', departamento:'Recursos Humanos', oficio:'OF-4', autor:'Autor ficticio', desde:'2025-02-01', hasta:'2025-03-02'});
});

test('se puede buscar con cada filtro añadido manualmente y sin consulta inicial', () => {
    for (const [clave, valor] of Object.entries({buscar:'alumbrado', categoria:'Actas', departamento:'Tesorería', oficio:'OF-23', autor:'Autor', desde:'2025-01-01', hasta:'2025-12-31'})) {
        const prueba = iniciar(); const c = prueba.controles;
        c['abrir-busqueda-asistida'].listeners.click();
        c[`asistido-${clave}`].value = valor;
        c[`asistido-${clave}`].listeners.input();
        c['form-busqueda-asistida'].listeners.submit({preventDefault() {}});
        assert.deepEqual(Object.fromEntries(new URLSearchParams(prueba.destino().slice(2))), {[clave]:valor});
    }
});

test('se rechazan rangos invertidos y se conservan filtros manuales al editar la consulta', () => {
    const prueba = iniciar(); const c = prueba.controles;
    c['busqueda-global'].value = 'contratos'; c['abrir-busqueda-asistida'].listeners.click();
    c['asistido-autor'].value = 'Autor'; c['asistido-autor'].listeners.input();
    c['editar-consulta-asistida'].listeners.click();
    c['busqueda-global'].value = 'informes'; c['abrir-busqueda-asistida'].listeners.click();
    assert.equal(c['asistido-categoria'].value, 'Informes');
    assert.equal(c['asistido-autor'].value, 'Autor');
    c['asistido-desde'].value = '2026-05-01'; c['asistido-hasta'].value = '2026-04-01';
    c['form-busqueda-asistida'].listeners.submit({preventDefault() {}});
    assert.equal(prueba.destino(), undefined);
    assert.match(c['filtros-sugeridos'].textContent, /fecha inicial/);
    c['asistido-desde'].value = '10000-01-01'; c['asistido-hasta'].value = '';
    c['form-busqueda-asistida'].listeners.submit({preventDefault() {}});
    assert.equal(prueba.destino(), undefined);
    assert.match(c['filtros-sugeridos'].textContent, /cuatro cifras/);
});

test('los reconocidos se muestran primero y los adicionales conservan sus valores al plegarse', () => {
    const prueba = iniciar(); const c = prueba.controles;
    c['busqueda-global'].value = 'contratos de Tesorería';
    c['abrir-busqueda-asistida'].listeners.click();
    assert.equal(c['filtros-reconocidos'].childElementCount, 2);
    assert.equal(c['filtros-adicionales'].childElementCount, 5);
    c['agregar-filtros'].open = true;
    c['asistido-autor'].value = 'Autor ficticio'; c['asistido-autor'].listeners.input();
    assert.equal(c['filtros-adicionales-activos'].textContent, '(1 activo)');
    c['agregar-filtros'].open = false; c['agregar-filtros'].open = true;
    assert.equal(c['asistido-autor'].value, 'Autor ficticio');
    c['agregar-filtros'].open = false;
    c['form-busqueda-asistida'].listeners.submit({preventDefault() {}});
    assert.equal(new URLSearchParams(prueba.destino().slice(2)).get('autor'), 'Autor ficticio');
});

test('se abre la sección adicional si un campo requiere corregirse', () => {
    const prueba = iniciar(); const c = prueba.controles;
    c['abrir-busqueda-asistida'].listeners.click();
    c['form-busqueda-asistida'].checkValidity = () => false;
    c['form-busqueda-asistida'].listeners.submit({preventDefault() {}});
    assert.equal(c['agregar-filtros'].open, true);
    assert.equal(prueba.destino(), undefined);
});

test('el folio ofrece búsqueda global sin navegar ni alterar el filtro documental', () => {
    const prueba = iniciar(); const c = prueba.controles;
    c['busqueda-global'].value = 'expediente EXP-2025-000123';
    c['abrir-busqueda-asistida'].listeners.click();
    assert.equal(prueba.destino(), undefined);
    assert.equal(c['filtros-reconocidos'].childElementCount, 0);
    assert.equal(c['filtros-sugeridos'].agregados[1].href, '/buscar?q=exp-2025-000123');
});

test('la interfaz muestra dudas temporales sin aplicar fechas', () => {
    const prueba = iniciar(); const c = prueba.controles;
    c['busqueda-global'].value = 'informes de marzo';
    c['abrir-busqueda-asistida'].listeners.click();
    assert.equal(c['asistido-categoria'].value, 'Informes');
    assert.equal(c['asistido-desde'].value, '');
    assert.equal(c['asistido-hasta'].value, '');
    assert.match(c['filtros-sugeridos'].textContent, /año/);
});

test('los casos sin cambios deliberados siguen coincidiendo con las reglas anteriores', () => {
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
    const consultas = ['', '   ', 'documento', '%%%_@',
        'contratos de Obras Públicas marzo 2025', 'contrato de alumbrado del año pasado',
        'certificados Tesorería', 'inventarios recursos humanos',
        'informe febrero 2024', 'informe febrero 2023', 'oficios sin número', 'archivo documentos',
        'café-público / foo_bar', 'x'.repeat(250), 'TESORERIA', 'oficio número A-1'];
    for (const consulta of consultas) {
        const esperado = JSON.parse(JSON.stringify(viejo(consulta)));
        const obtenido = JSON.parse(JSON.stringify(actual.window.sigedInterpretarBusqueda(consulta, categorias, areas)));
        assert.deepEqual(obtenido, esperado, consulta);
    }
});

test('cambio deliberado: dos categorías no seleccionan una al azar', () => {
    const categorias = ['Actas', 'Bitacoras']; const areas = [];
    const contexto = {window: {}};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'app', 'static', 'interprete_busqueda.js'), 'utf8'), contexto);
    const resultado = contexto.window.sigedInterpretarBusqueda.detallar('bitácoras y ACTAS', categorias, areas);
    assert.equal(resultado.filtros.categoria, undefined);
    assert.match(resultado.avisos.join(' '), /varias categorías/);
    const anterior = require('./fixtures/interprete_anterior.js')(categorias, areas)('bitácoras y ACTAS');
    assert.equal(anterior.categoria, 'Actas');
});
