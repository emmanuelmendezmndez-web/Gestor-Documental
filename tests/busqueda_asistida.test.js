// Ejecuta los archivos reales en un DOM simulado, en el mismo orden del navegador.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function iniciar(config = {}, ruta = '/inicio') {
    const controles = {};
    for (const id of ['busqueda-asistida', 'abrir-busqueda-asistida', 'cerrar-busqueda-asistida',
        'busqueda-global', 'consulta-asistida-texto', 'editar-consulta-asistida', 'filtros-sugeridos', 'form-busqueda-asistida',
        'filtros-reconocidos', 'filtros-adicionales', 'agregar-filtros', 'sin-filtros-reconocidos', 'filtros-adicionales-activos', 'instruccion-contextual', 'proponer-contexto', 'propuesta-contextual',
        ...['buscar', 'categoria', 'departamento', 'oficio', 'autor', 'desde', 'hasta'].map(clave => `asistido-${clave}`)]) {
        controles[id] = { value: '', hidden: true, listeners: {}, addEventListener(tipo, fn) { this.listeners[tipo] = fn; }, append(...items) { this.agregados = items; }, replaceChildren() { this.agregados = []; this.textContent = ''; }, after(item) { this.siguiente = item; } };
    }
    const dialogo = controles['busqueda-asistida'];
    const rapidos = ['contratos', 'obras', 'mes'].map(clave => ({dataset:{busquedaRapida:clave}, textContent:clave,
        listeners:{}, addEventListener(tipo, fn) { this.listeners[tipo] = fn; }}));
    dialogo.querySelector = () => null;
    dialogo.querySelectorAll = () => rapidos;
    dialogo.showModal = () => { dialogo.open = true; };
    dialogo.close = () => { dialogo.open = false; dialogo.listeners.close?.(); };
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
        sigedClippyConfig: config,
        location: { pathname: ruta, assign: valor => { destino = valor; } },
        listeners: {}, addEventListener(tipo, fn) { this.listeners[tipo] = fn; },
    };
    class Fecha extends Date {
        constructor(...args) { super(...(args.length ? args : ['2026-10-28T12:00:00'])); }
    }
    const eventosDocumento = {};
    class FormularioGlobal { constructor() { this.method = 'get'; this.action = 'http://localhost/buscar'; } }
    const contexto = { window, Date: Fecha, URLSearchParams, URL, console, HTMLFormElement:FormularioGlobal, FormData:class { get(){ return 'contratos'; } },
        sessionStorage: { getItem: () => '1', setItem() {} },
        fetch: async () => ({ ok: true, json: async () => ({}) }),
        document: { getElementById: id => controles[id], querySelector: () => null, addEventListener(tipo, fn) { eventosDocumento[tipo] = fn; }, createElement: () => ({
            children: [], listeners: {}, style: {}, setAttribute() {}, focus() {}, append(...items) { this.children.push(...items); },
            replaceChildren() { this.children = []; }, addEventListener(tipo, fn) { this.listeners[tipo] = fn; },
        }) },
    };
    for (const nombre of ['memoria_temporal.js', 'interprete_busqueda.js', 'interprete_contextual.js', 'clasificador_ayuda_clippy.js', 'catalogo_ayuda_clippy.js', 'busqueda_asistida.js']) {
        const archivo = path.join(__dirname, '..', 'app', 'static', nombre);
        vm.runInNewContext(fs.readFileSync(archivo, 'utf8'), contexto);
        if (nombre === 'memoria_temporal.js') window.crearMemoriaTemporal = () => { window.memoriaPrueba = contexto.crearMemoriaTemporal(); return window.memoriaPrueba; };
        if (nombre === 'interprete_busqueda.js') contexto.sigedInterpretarBusqueda = window.sigedInterpretarBusqueda;
        if (nombre === 'interprete_contextual.js') window.sigedInterpretarContexto = (texto, ctx) => contexto.sigedInterpretarContexto(texto, ctx, window.sigedInterpretarBusqueda.detallar);
        if (nombre === 'clasificador_ayuda_clippy.js') window.sigedClasificarAyuda = contexto.sigedClasificarAyuda;
        if (nombre === 'catalogo_ayuda_clippy.js') window.sigedConsultarAyuda = contexto.sigedConsultarAyuda;
    }
    return { interpretar: texto => JSON.parse(JSON.stringify(window.sigedInterpretarBusqueda(
        texto, window.sigedOpcionesBusqueda.categorias, window.sigedOpcionesBusqueda.areas))), controles, destino: () => destino,
        memoria: window.memoriaPrueba, eventosVentana: window.listeners, eventosDocumento, FormularioGlobal, rapidos };
}

test('Con Clippy clasifica ayuda desde la barra sin generar filtros', () => {
    const p = iniciar({puedeVer:true, puedeSubir:true}, '/inicio'), c = p.controles;
    c['busqueda-global'].value = '¿Cómo subo un documento?'; c['abrir-busqueda-asistida'].listeners.click();
    assert.match(c['propuesta-contextual'].textContent, /Abre Subir documento desde el menú/);
    assert.equal(JSON.stringify(p.memoria.consultar().filtros), '{}'); assert.equal(p.destino(), undefined);
});
test('la ayuda de búsqueda desde Inicio indica dónde escribir y cómo precisar resultados', () => {
    const p = iniciar({puedeVer:true, puedeVerExpedientes:true}, '/inicio'), c = p.controles;
    c['busqueda-global'].value = '¿Cómo busco un documento?'; c['abrir-busqueda-asistida'].listeners.click();
    assert.match(c['propuesta-contextual'].textContent, /barra superior y pulsa Buscar/);
    assert.match(c['propuesta-contextual'].textContent, /filtros de Biblioteca/);
    assert.equal(JSON.stringify(p.memoria.consultar().filtros), '{}');
});
test('Con Clippy prepara búsquedas desde la barra y pide aclaración para intenciones ambiguas', () => {
    const p = iniciar({puedeVer:true, puedeVerExpedientes:true}, '/'), c = p.controles;
    c['busqueda-global'].value = 'Busca contratos de 2025'; c['abrir-busqueda-asistida'].listeners.click();
    assert.equal(c['asistido-categoria'].value, 'Contratos'); assert.equal(c['asistido-desde'].value, '2025-01-01');
    c['asistido-autor'].value = 'Ejemplo'; c['asistido-autor'].listeners.input();
    const antes = JSON.stringify(p.memoria.consultar());
    c['editar-consulta-asistida'].listeners.click(); c['busqueda-global'].value = '¿Cómo?'; c['abrir-busqueda-asistida'].listeners.click();
    assert.match(c['propuesta-contextual'].agregados[0].textContent, /ayuda o iniciar una búsqueda/);
    assert.equal(JSON.stringify(p.memoria.consultar()), antes); assert.equal(p.destino(), undefined);
});
test('corrección desde la barra usa la interacción anterior y espera confirmación', () => {
    const p = iniciar({puedeVer:true}, '/'), c = p.controles;
    c['busqueda-global'].value = 'Contratos de Tesorería de marzo de 2025'; c['abrir-busqueda-asistida'].listeners.click();
    c['asistido-autor'].value = 'Ejemplo'; c['asistido-autor'].listeners.input();
    const antes = JSON.stringify(p.memoria.consultar());
    c['editar-consulta-asistida'].listeners.click(); c['busqueda-global'].value = 'Mejor de abril'; c['abrir-busqueda-asistida'].listeners.click();
    assert.match(c['propuesta-contextual'].agregados[0].textContent, /2025-04-01/);
    assert.equal(JSON.stringify(p.memoria.consultar()), antes);
    c['propuesta-contextual'].agregados[1].listeners.click();
    assert.equal(c['asistido-desde'].value, '2025-04-01'); assert.equal(c['asistido-autor'].value, 'Ejemplo');
});
test('el envío global conserva su acción GET sin interceptarse', () => {
    const p = iniciar(); let detenido = false;
    p.eventosDocumento.submit({target:new p.FormularioGlobal(), preventDefault(){detenido = true;}});
    assert.equal(detenido, false); assert.equal(p.destino(), undefined);
    const plantilla = fs.readFileSync(path.join(__dirname, '../app/templates/base.html'), 'utf8');
    assert.match(plantilla, /<form action="\/buscar" method="get" class="busqueda-global"/);
    assert.match(plantilla, /name="q"/);
});

test('ayuda respeta capacidades de lector, editor y administrador sin cambiar filtros', () => {
    for (const [config, ruta, pregunta, patron] of [
        [{puedeVer:true, puedeVerExpedientes:true, puedeGestionarExpedientes:false}, '/expedientes', 'Cómo crear un expediente', /administradora/],
        [{puedeVer:true, puedePapelera:true, puedeRestaurar:true, puedeEliminar:false}, '/papelera', 'Cómo eliminar definitivamente', /administradora/],
        [{puedeVer:true, puedePapelera:true, puedeRestaurar:true, puedeEliminar:true}, '/papelera', 'Cómo eliminar definitivamente', /no se puede deshacer/],
        [{puedeVer:true}, '/inicio', 'Por qué no puedo eliminar', /dependen de tu cuenta/]
    ]) {
        const p = iniciar(config, ruta), c = p.controles;
        c['busqueda-global'].value = 'Contratos de Tesorería de marzo de 2025'; c['abrir-busqueda-asistida'].listeners.click();
        const anterior = JSON.stringify(p.memoria.consultar());
        c['instruccion-contextual'].value = pregunta; c['proponer-contexto'].listeners.click();
        assert.match(c['propuesta-contextual'].textContent, patron);
        assert.equal(JSON.stringify(p.memoria.consultar()), anterior); assert.equal(p.destino(), undefined);
    }
});
test('la ayuda desde el formulario reconoce la pantalla de nuevo expediente', () => {
    const p = iniciar({puedeVer:true, puedeVerExpedientes:true, puedeGestionarExpedientes:true}, '/expedientes/nuevo');
    const c = p.controles;
    c['busqueda-global'].value = 'Cómo crear un expediente';
    c['abrir-busqueda-asistida'].listeners.click();
    assert.match(c['propuesta-contextual'].textContent, /Nuevo expediente.*nombre o asunto.*descripción.*folio/i);
    assert.equal(p.destino(), undefined);
});

test('intención ambigua exige elegir y prepara búsqueda sin ejecutarla', () => {
    const p = iniciar({puedeVer:true}, '/biblioteca'), c = p.controles;
    c['busqueda-global'].value = 'contratos de 2025'; c['abrir-busqueda-asistida'].listeners.click();
    const anterior = JSON.stringify(p.memoria.consultar());
    c['instruccion-contextual'].value = '¿Cómo?'; c['proponer-contexto'].listeners.click();
    assert.match(c['propuesta-contextual'].agregados[0].textContent, /ayuda o iniciar una búsqueda/);
    c['form-busqueda-asistida'].listeners.submit({preventDefault(){}});
    assert.equal(p.destino(), undefined); assert.equal(JSON.stringify(p.memoria.consultar()), anterior);
    c['propuesta-contextual'].agregados[2].listeners.click();
    assert.match(c['propuesta-contextual'].agregados[0].textContent, /Comenzar una consulta nueva/);
    assert.equal(JSON.stringify(p.memoria.consultar()), anterior); assert.equal(p.destino(), undefined);
});

test('propuestas contextuales requieren confirmación y permiten cancelar sin buscar', () => {
    const p = iniciar(), c = p.controles;
    c['busqueda-global'].value = 'Contratos de Tesorería de marzo de 2025'; c['abrir-busqueda-asistida'].listeners.click();
    c['asistido-categoria'].value = 'Actas'; c['asistido-categoria'].listeners.input();
    const antes = JSON.stringify(p.memoria.consultar());
    c['instruccion-contextual'].value = 'Mejor de abril'; c['proponer-contexto'].listeners.click();
    assert.equal(JSON.stringify(p.memoria.consultar()), antes);
    c['propuesta-contextual'].agregados[2].listeners.click();
    assert.equal(JSON.stringify(p.memoria.consultar()), antes);
    c['proponer-contexto'].listeners.click(); c['propuesta-contextual'].agregados[1].listeners.click();
    assert.equal(c['asistido-desde'].value, '2025-04-01'); assert.equal(c['asistido-hasta'].value, '2025-04-30');
    assert.equal(c['asistido-categoria'].value, 'Actas'); assert.equal(c['asistido-departamento'].value, 'Tesorería');
    assert.equal(p.destino(), undefined);
});

test('quitar departamento manual requiere confirmación y conserva los demás criterios', () => {
    const p = iniciar(), c = p.controles;
    c['busqueda-global'].value = 'Contratos de Tesorería de marzo de 2025'; c['abrir-busqueda-asistida'].listeners.click();
    c['asistido-buscar'].value = 'alumbrado'; c['asistido-buscar'].listeners.input();
    c['asistido-departamento'].value = 'Tesorería'; c['asistido-departamento'].listeners.input();
    const antes = JSON.stringify(p.memoria.consultar());
    c['instruccion-contextual'].value = 'quitar tesoreria'; c['proponer-contexto'].listeners.click();
    assert.match(c['propuesta-contextual'].agregados[0].textContent, /Departamento: quitar/);
    assert.equal(JSON.stringify(p.memoria.consultar()), antes);
    c['propuesta-contextual'].agregados[2].listeners.click(); assert.equal(JSON.stringify(p.memoria.consultar()), antes);
    c['proponer-contexto'].listeners.click(); c['propuesta-contextual'].agregados[1].listeners.click();
    assert.equal(c['asistido-departamento'].value, '');
    assert.equal(c['asistido-categoria'].value, 'Contratos'); assert.equal(c['asistido-buscar'].value, 'alumbrado');
    assert.equal(c['asistido-desde'].value, '2025-03-01'); assert.equal(c['asistido-hasta'].value, '2025-03-31');
    const despues = JSON.stringify(p.memoria.consultar());
    c['instruccion-contextual'].value = 'quitar tesorería'; c['proponer-contexto'].listeners.click();
    assert.match(c['propuesta-contextual'].textContent, /no está aplicado/);
    assert.equal(JSON.stringify(p.memoria.consultar()), despues); assert.equal(p.destino(), undefined);
});

test('limpiar, reiniciar y consulta nueva tienen ciclos distintos', () => {
    const p = iniciar(), c = p.controles;
    c['busqueda-global'].value = 'informes de marzo'; c['abrir-busqueda-asistida'].listeners.click();
    c['asistido-autor'].value = 'Ejemplo'; c['asistido-autor'].listeners.input();
    const aplicar = texto => { c['instruccion-contextual'].value = texto; c['proponer-contexto'].listeners.click(); c['propuesta-contextual'].agregados[1].listeners.click(); };
    aplicar('Olvida los filtros');
    assert.equal(p.memoria.consultar().consulta, 'informes de marzo');
    assert.equal(JSON.stringify(p.memoria.consultar().filtros), '{}');
    assert.equal(p.memoria.consultar().manuales.length, 0); assert.equal(p.memoria.consultar().pendientes.length, 0);
    aplicar('contratos de Tesorería'); assert.equal(c['asistido-categoria'].value, 'Contratos');
    aplicar('Empieza de nuevo'); assert.equal(p.memoria.consultar().consulta, ''); assert.equal(c['asistido-categoria'].value, '');
    assert.equal(p.destino(), undefined);
});

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

test('editar la misma consulta mantiene contexto y las aclaraciones resueltas', () => {
    const prueba = iniciar(), c = prueba.controles;
    c['busqueda-global'].value = 'informes de marzo'; c['abrir-busqueda-asistida'].listeners.click();
    c['filtros-sugeridos'].siguiente.children.find(x => x.textContent === '2026').listeners.click();
    const anterior = prueba.memoria.consultar();
    c['editar-consulta-asistida'].listeners.click(); c['abrir-busqueda-asistida'].listeners.click();
    assert.deepEqual(prueba.memoria.consultar(), anterior);
    assert.equal(c['asistido-desde'].value, '2026-03-01');
    assert.equal(c['filtros-sugeridos'].siguiente.hidden, true);
});

test('cambiar consulta permite volver sin perder ediciones o aceptar una interacción limpia', () => {
    const prueba = iniciar(), c = prueba.controles;
    c['busqueda-global'].value = 'contratos de obras'; c['abrir-busqueda-asistida'].listeners.click();
    c['asistido-autor'].value = 'Autor previo'; c['asistido-autor'].listeners.input();
    c['editar-consulta-asistida'].listeners.click();
    c['busqueda-global'].value = 'informes'; c['abrir-busqueda-asistida'].listeners.click();
    let guia = c['filtros-sugeridos'].siguiente;
    assert.match(c['filtros-sugeridos'].textContent, /descartará/);
    guia.children.find(x => x.textContent === 'Volver a consulta anterior').listeners.click();
    assert.equal(c['busqueda-global'].value, 'contratos de obras');
    assert.equal(c['asistido-autor'].value, 'Autor previo');
    assert.equal(prueba.memoria.consultar().consulta, 'contratos de obras');
    c['editar-consulta-asistida'].listeners.click(); c['busqueda-global'].value = 'informes';
    c['abrir-busqueda-asistida'].listeners.click(); guia = c['filtros-sugeridos'].siguiente;
    guia.children.find(x => x.textContent === 'Iniciar búsqueda nueva').listeners.click();
    assert.equal(prueba.memoria.consultar().consulta, 'informes');
    assert.equal(c['asistido-autor'].value, '');
    assert.deepEqual(JSON.parse(JSON.stringify(prueba.memoria.consultar().filtros)), {categoria:'Informes'});
    assert.deepEqual(JSON.parse(JSON.stringify(prueba.memoria.consultar().pendientes)), []);
});

test('cancelar, cierre externo, pagehide y finalizar descartan la interacción', () => {
    for (const modo of ['cancelar', 'escape', 'pagehide', 'finalizar']) {
        const prueba = iniciar(), c = prueba.controles;
        c['busqueda-global'].value = 'contratos'; c['abrir-busqueda-asistida'].listeners.click();
        c['asistido-autor'].value = 'Autor temporal'; c['asistido-autor'].listeners.input();
        if (modo === 'cancelar') c['cerrar-busqueda-asistida'].listeners.click();
        if (modo === 'escape') c['busqueda-asistida'].close();
        if (modo === 'pagehide') prueba.eventosVentana.pagehide();
        if (modo === 'finalizar') c['form-busqueda-asistida'].listeners.submit({preventDefault() {}});
        assert.equal(prueba.memoria.consultar(), null, modo);
        assert.equal(prueba.memoria.obtenerUltimoValido(), null, modo);
        assert.equal(c['asistido-autor'].value, '', modo);
        if (modo === 'finalizar') assert.equal(new URLSearchParams(prueba.destino().slice(2)).get('autor'), 'Autor temporal');
    }
});

test('el cierre diferido no reutiliza una interacción cancelada ni borra una nueva', () => {
    const prueba = iniciar(), c = prueba.controles, dialogo = c['busqueda-asistida'];
    dialogo.close = () => { dialogo.open = false; }; // Simula close entregado después por el navegador.
    c['busqueda-global'].value = 'contratos'; c['abrir-busqueda-asistida'].listeners.click();
    c['asistido-autor'].value = 'Autor anterior'; c['asistido-autor'].listeners.input();
    c['cerrar-busqueda-asistida'].listeners.click();
    assert.equal(prueba.memoria.consultar(), null);
    c['busqueda-global'].value = 'informes'; c['abrir-busqueda-asistida'].listeners.click();
    assert.equal(c['asistido-autor'].value, '');
    dialogo.listeners.close();
    assert.equal(prueba.memoria.consultar().consulta, 'informes');
});

test('editar conserva la interacción aunque el evento close llegue tras reabrir', () => {
    const prueba = iniciar(), c = prueba.controles, dialogo = c['busqueda-asistida'];
    dialogo.close = () => { dialogo.open = false; };
    c['busqueda-global'].value = 'contratos'; c['abrir-busqueda-asistida'].listeners.click();
    c['asistido-autor'].value = 'Autor conservado'; c['asistido-autor'].listeners.input();
    c['editar-consulta-asistida'].listeners.click(); c['abrir-busqueda-asistida'].listeners.click();
    dialogo.listeners.close();
    assert.equal(prueba.memoria.consultar().filtros.autor, 'Autor conservado');
    dialogo.close(); // Cierre externo, antes de que se notifique close.
    c['busqueda-global'].value = 'informes'; c['abrir-busqueda-asistida'].listeners.click();
    assert.equal(prueba.memoria.consultar().consulta, 'informes');
    assert.equal(c['asistido-autor'].value, '');
});

test('fechas temporalmente inválidas no destruyen el último estado válido ni prioridad manual', () => {
    const prueba = iniciar(), c = prueba.controles;
    c['busqueda-global'].value = 'contratos'; c['abrir-busqueda-asistida'].listeners.click();
    c['asistido-hasta'].value = '2026-01-01'; c['asistido-hasta'].listeners.input();
    c['asistido-desde'].value = '2026-02-01'; c['asistido-desde'].listeners.input();
    assert.equal(prueba.memoria.obtenerUltimoValido().filtros.desde, undefined);
    assert.equal(prueba.memoria.consultar().manuales.includes('desde'), true);
    c['asistido-hasta'].value = '2026-03-01'; c['asistido-hasta'].listeners.input();
    assert.equal(prueba.memoria.consultar().filtros.desde, '2026-02-01');
    assert.equal(prueba.memoria.consultar().filtros.hasta, '2026-03-01');
});

test('una búsqueda rápida también pide confirmación antes de descartar filtros manuales', () => {
    const prueba = iniciar(), c = prueba.controles;
    c['busqueda-global'].value = 'informes'; c['abrir-busqueda-asistida'].listeners.click();
    c['asistido-autor'].value = 'Autor'; c['asistido-autor'].listeners.input();
    prueba.rapidos[0].listeners.click();
    let guia = c['filtros-sugeridos'].siguiente;
    assert.match(c['filtros-sugeridos'].textContent, /descartará/);
    guia.children.find(x => x.textContent === 'Volver a consulta anterior').listeners.click();
    assert.equal(c['asistido-autor'].value, 'Autor');
    assert.equal(c['asistido-categoria'].value, 'Informes');
    prueba.rapidos[0].listeners.click(); guia = c['filtros-sugeridos'].siguiente;
    guia.children.find(x => x.textContent === 'Iniciar búsqueda nueva').listeners.click();
    assert.equal(c['asistido-autor'].value, '');
    assert.equal(c['asistido-categoria'].value, 'Contratos');
    assert.equal(prueba.destino(), undefined);
});

test('la intención de expediente se registra sin navegar y no se comparte entre instancias', () => {
    const uno = iniciar(), dos = iniciar();
    uno.controles['busqueda-global'].value = 'expediente EXP-2025-000123';
    uno.controles['abrir-busqueda-asistida'].listeners.click();
    dos.controles['busqueda-global'].value = 'informes'; dos.controles['abrir-busqueda-asistida'].listeners.click();
    assert.equal(uno.memoria.consultar().intencion, 'expedientes');
    assert.equal(dos.memoria.consultar().intencion, 'documentos');
    uno.controles['cerrar-busqueda-asistida'].listeners.click();
    assert.equal(uno.memoria.consultar(), null);
    assert.equal(dos.memoria.consultar().consulta, 'informes');
    assert.equal(uno.destino(), undefined);
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

test('se rechazan rangos invertidos después de confirmar una consulta nueva', () => {
    const prueba = iniciar(); const c = prueba.controles;
    c['busqueda-global'].value = 'contratos'; c['abrir-busqueda-asistida'].listeners.click();
    c['asistido-autor'].value = 'Autor'; c['asistido-autor'].listeners.input();
    c['editar-consulta-asistida'].listeners.click();
    c['busqueda-global'].value = 'informes'; c['abrir-busqueda-asistida'].listeners.click();
    c['filtros-sugeridos'].siguiente.children.find(x => x.textContent === 'Iniciar búsqueda nueva').listeners.click();
    assert.equal(c['asistido-categoria'].value, 'Informes');
    assert.equal(c['asistido-autor'].value, '');
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
    assert.match(c['filtros-sugeridos'].siguiente.children[0].textContent, /año/);
});

test('elegir un año solo modifica fechas y conserva el filtro manual', () => {
    const prueba = iniciar(), c = prueba.controles;
    c['busqueda-global'].value = 'informes de marzo'; c['abrir-busqueda-asistida'].listeners.click();
    c['asistido-categoria'].value = 'Actas'; c['asistido-categoria'].listeners.input();
    const guia = c['filtros-sugeridos'].siguiente;
    guia.children.find(x => x.textContent === '2026').listeners.click();
    assert.equal(c['asistido-desde'].value, '2026-03-01');
    assert.equal(c['asistido-hasta'].value, '2026-03-31');
    assert.equal(c['asistido-categoria'].value, 'Actas');
    assert.equal(prueba.destino(), undefined);
});

test('una aclaración no sobrescribe fechas editadas; puede omitirse y reiniciarse', () => {
    const prueba = iniciar(), c = prueba.controles;
    c['busqueda-global'].value = 'informes de marzo'; c['abrir-busqueda-asistida'].listeners.click();
    c['asistido-desde'].value = '2020-01-01'; c['asistido-desde'].listeners.input();
    let guia = c['filtros-sugeridos'].siguiente;
    guia.children.find(x => x.textContent === '2026').listeners.click();
    assert.equal(c['asistido-desde'].value, '2020-01-01');
    assert.match(guia.children[0].textContent, /conservaron/);
    guia.children.find(x => x.textContent === 'Dejar sin aplicar').listeners.click();
    assert.equal(guia.hidden, true);
    c['editar-consulta-asistida'].listeners.click(); c['abrir-busqueda-asistida'].listeners.click();
    guia = c['filtros-sugeridos'].siguiente;
    assert.equal(guia.hidden, true);
    assert.equal(c['asistido-desde'].value, '2020-01-01');
});

test('obras permite elegir tema o departamento sin modificar filtros manuales', () => {
    const prueba = iniciar(), c = prueba.controles;
    c['busqueda-global'].value = 'contratos de obras'; c['abrir-busqueda-asistida'].listeners.click();
    assert.equal(c['asistido-buscar'].value, 'obras');
    c['form-busqueda-asistida'].listeners.submit({preventDefault() {}});
    assert.equal(prueba.destino(), undefined);
    assert.match(c['filtros-sugeridos'].textContent, /aclaración/);
    c['filtros-sugeridos'].siguiente.children.find(x => x.textContent === 'Departamento Obras Públicas').listeners.click();
    assert.equal(c['asistido-departamento'].value, 'Obras Públicas');
    assert.equal(c['asistido-buscar'].value, '');
    assert.equal(c['asistido-categoria'].value, 'Contratos');
    assert.equal(prueba.destino(), undefined);
});

test('se aclaran fecha y categoría sucesivamente sin ejecutar la búsqueda', () => {
    const prueba = iniciar(), c = prueba.controles;
    c['busqueda-global'].value = 'contratos y actas 03/04/2026'; c['abrir-busqueda-asistida'].listeners.click();
    const guia = c['filtros-sugeridos'].siguiente;
    guia.children.find(x => x.textContent === 'Actas').listeners.click();
    assert.equal(c['asistido-categoria'].value, 'Actas');
    guia.children.find(x => x.textContent === '2026-04-03').listeners.click();
    assert.equal(c['asistido-desde'].value, '2026-04-03');
    assert.equal(c['asistido-hasta'].value, '2026-04-03');
    assert.equal(prueba.destino(), undefined);
});

test('dejar sin aplicar la duda de obras elimina el tema propuesto no editado', () => {
    const prueba = iniciar(), c = prueba.controles;
    c['busqueda-global'].value = 'contratos de obras'; c['abrir-busqueda-asistida'].listeners.click();
    c['filtros-sugeridos'].siguiente.children.find(x => x.textContent === 'Dejar sin aplicar').listeners.click();
    assert.equal(c['asistido-buscar'].value, '');
    assert.equal(c['asistido-departamento'].value, '');
});

test('cada decisión sobre obras genera exactamente la URL confirmada', () => {
    const casos = [
        ['Tema documental', {buscar:'obras', categoria:'Contratos'}],
        ['Departamento Obras Públicas', {categoria:'Contratos', departamento:'Obras Públicas'}],
        ['Dejar sin aplicar', {categoria:'Contratos'}],
    ];
    for (const [decision, esperado] of casos) {
        const prueba = iniciar(), c = prueba.controles;
        c['busqueda-global'].value = 'contratos de obras'; c['abrir-busqueda-asistida'].listeners.click();
        c['filtros-sugeridos'].siguiente.children.find(boton => boton.textContent === decision).listeners.click();
        c['form-busqueda-asistida'].listeners.submit({preventDefault() {}});
        assert.ok(prueba.destino().startsWith('/?'));
        assert.deepEqual(Object.fromEntries(new URLSearchParams(prueba.destino().slice(2))), esperado, decision);
    }
});

test('las decisiones sobre obras respetan texto, área y categoría editados manualmente', () => {
    for (const decision of ['Tema documental', 'Departamento Obras Públicas', 'Dejar sin aplicar']) {
        const prueba = iniciar(), c = prueba.controles;
        c['busqueda-global'].value = 'contratos de obras'; c['abrir-busqueda-asistida'].listeners.click();
        c['asistido-buscar'].value = 'obras de alumbrado'; c['asistido-buscar'].listeners.input();
        c['asistido-categoria'].value = 'Actas'; c['asistido-categoria'].listeners.input();
        c['filtros-sugeridos'].siguiente.children.find(boton => boton.textContent === decision).listeners.click();
        assert.equal(c['asistido-buscar'].value, 'obras de alumbrado', decision);
        assert.equal(c['asistido-categoria'].value, 'Actas', decision);
        c['form-busqueda-asistida'].listeners.submit({preventDefault() {}});
        const params = Object.fromEntries(new URLSearchParams(prueba.destino().slice(2)));
        assert.deepEqual(params, decision === 'Departamento Obras Públicas'
            ? {buscar:'obras de alumbrado', categoria:'Actas', departamento:'Obras Públicas'}
            : {buscar:'obras de alumbrado', categoria:'Actas'}, decision);
    }
    const prueba = iniciar(), c = prueba.controles;
    c['busqueda-global'].value = 'contratos de obras'; c['abrir-busqueda-asistida'].listeners.click();
    c['asistido-departamento'].value = 'Tesorería'; c['asistido-departamento'].listeners.input();
    const guia = c['filtros-sugeridos'].siguiente;
    guia.children.find(boton => boton.textContent === 'Departamento Obras Públicas').listeners.click();
    assert.equal(c['asistido-departamento'].value, 'Tesorería');
    assert.match(guia.children[0].textContent, /conservaron/);
    assert.equal(prueba.destino(), undefined);
});

test('dos años se presentan como alternativas y no como una búsqueda ejecutada', () => {
    const prueba = iniciar(), c = prueba.controles;
    c['busqueda-global'].value = 'contratos de 2025 y 2026'; c['abrir-busqueda-asistida'].listeners.click();
    const guia = c['filtros-sugeridos'].siguiente;
    assert.match(guia.children[0].textContent, /solo admite un intervalo/);
    guia.children.find(x => x.textContent === '2025-01-01 a 2025-12-31').listeners.click();
    assert.equal(c['asistido-desde'].value, '2025-01-01');
    assert.equal(c['asistido-hasta'].value, '2025-12-31');
    assert.equal(prueba.destino(), undefined);
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
