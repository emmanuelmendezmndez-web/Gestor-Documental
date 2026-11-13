const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function iniciar(ruta = '/inicio', config = {}, opciones = {}) {
    let reloj = 10000, secuencia = 0, reposos = 0;
    const reacciones = [], colaAnimaciones = [], sonidos = [];
    const movimiento = {matches:opciones.movimientoReducido ?? true};
    const timers = new Map(), eventos = {}, dichos = [], movimientos = [], clases = new Set();
    const figura = {style:{}, classList:{add(c){clases.add(c);}, remove(c){clases.delete(c);}, contains(c){return clases.has(c);}}, matches:()=>false, setAttribute(){}, addEventListener(tipo, fn){ this[tipo] = fn; }};
    const busqueda = {open:false}, confirmacion = {open:false};
    const selector = {open:false}, compositor = {addEventListener(){}};
    const texto = {addEventListener(){}}, envio = {activo:false, getAttribute(){return this.activo ? 'true' : null;}};
    const elementos = {'busqueda-asistida':busqueda, 'dialogo-confirmacion':confirmacion,
        ...(opciones.mensajeria ? {mensajeria:{}, 'mensajeria-compositor':compositor,
            'mensajeria-texto':texto, 'mensajeria-enviar':envio, 'mensajeria-selector':selector} : {})};
    class Entrada { constructor(){ this.type='text'; this.value='ficticio'; this.dataset={clippyRead:'Búsqueda'}; } hasAttribute(){return true;} closest(){return null;} }
    const document = {readyState:'complete', addEventListener(tipo, fn){ (eventos[tipo] ||= []).push(fn); },
        removeEventListener(tipo, fn){ eventos[tipo] = (eventos[tipo] || []).filter(handler => handler !== fn); },
        getElementById(id){return elementos[id] || null;},
        querySelector(q){return q === '.clippy' ? figura : null;},
        querySelectorAll(q){const rects = q.includes('#mensajeria-compositor') ? opciones.protegidos : opciones.controles;
            return (rects || []).map(rect => ({getClientRects:()=>[rect], getBoundingClientRect:()=>rect}));}};
    const agente = {_getIdleAnimation(){}, hasAnimation(nombre){return (opciones.animaciones || []).includes(nombre);}, _onQueueEmpty(){reposos++;}, _queue:{}, _balloon:{hide(){}, _balloon:{hide(){}}}, _animator:{_playSound(){sonidos.push('sonido');}},
        _addToQueue(fn){colaAnimaciones.push(fn);}, _playInternal(nombre, fin){reacciones.push(nombre); fin(nombre, 'exited');},
        speak(texto){dichos.push(texto);}, stop(){colaAnimaciones.length=0;}, moveTo(x,y){movimientos.push({x,y}); figura.style.top = String(y);}, show(){}};
    const window = {clippy:true, sigedClippyConfig:{basePath:'', usuarioId:1, nombre:'Prueba', ...config}, location:{pathname:ruta, search:opciones.search || ''},
        innerHeight:opciones.alto || 800, innerWidth:opciones.ancho || 1200, matchMedia:()=>movimiento, requestAnimationFrame(){}, addEventListener(){}, removeEventListener(){},
        sigedClippyPreferencias:opciones.preferencias && {then(fn){fn(opciones.preferencias);}},
        setTimeout(fn, ms){const id=++secuencia; timers.set(id,{fn, ms}); return id;}, clearTimeout(id){timers.delete(id);}};
    class Fecha extends Date { static now(){return reloj;} }
    const ctx = {window, document, clippy:{Animator:{States:{EXITED:'exited'}}, load(_nombre, fn){fn(agente);}}, Date:Fecha, URLSearchParams, HTMLElement:Entrada, HTMLInputElement:Entrada, getComputedStyle:()=>({display:'none'}), ResizeObserver:class {observe(){}}, console};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../app/static/clippy_asistente.js'), 'utf8'), ctx);
    return {busqueda, confirmacion, figura, dichos, eventos, Entrada, timers, movimientos, agente, reacciones, colaAnimaciones, movimiento, sonidos, document, selector, envio, texto, reposos:()=>reposos, avanzar(ms){reloj += ms;}, ejecutar(ms){const lista=[...timers.entries()].filter(([, t])=>t.ms===ms); for (const [id,t] of lista) {timers.delete(id); t.fn();}}};
}
test('Mensajería ofrece consejos propios aunque Biblioteca sea la sección habitual', () => {
    const p = iniciar('/mensajeria', {saludoEntrada:true}, {mensajeria:true, search:'?aviso=subido',
        preferencias:{experiencia:'habitual', secciones:['biblioteca'], rutina:'biblioteca'}});
    p.avanzar(3000); p.ejecutar(3000);
    assert.deepEqual(p.dichos, []);
    for (let i=0; i<6; i++) p.figura.click();
    assert.equal(new Set(p.dichos).size, 6);
    assert.match(p.dichos.join(' '), /panel izquierdo.*restricciones de acceso.*contador verde/);
    assert.doesNotMatch(p.dichos.join(' '), /Sueles usar|Documento subido/);
    p.figura.click();
    assert.equal(p.dichos.at(-1), p.dichos[0]);
});
test('la ayuda solicitada solo habla del apartado, y el saludo no recomienda hábitos', () => {
    const preferencias = {experiencia:'habitual', rutina:'biblioteca', secciones:['biblioteca']};
    const p = iniciar('/inicio', {saludoEntrada:true}, {preferencias});
    p.avanzar(3000);
    p.ejecutar(3000);
    p.figura.click();
    assert.equal(p.dichos.length, 2);
    assert.doesNotMatch(p.dichos[0], /Biblioteca|Sueles/);
    assert.equal(p.dichos[1], 'En Inicio puedes consultar indicadores, avisos y los documentos recientes.');
});
test('un hábito se recomienda una sola vez tras superar tres minutos sin actividad', () => {
    const p = iniciar('/inicio', {}, {preferencias:{experiencia:'habitual', secciones:['biblioteca']}});
    p.avanzar(100000);
    for (const fn of p.eventos.pointerdown) fn({});
    p.avanzar(80001);
    p.ejecutar(180001);
    assert.deepEqual(p.dichos, []);
    p.avanzar(99999);
    p.ejecutar(100000);
    assert.deepEqual(p.dichos, []);
    p.avanzar(1);
    p.ejecutar(1);
    assert.deepEqual(p.dichos, ['Sueles usar Biblioteca. ¿Quieres volver?']);
    p.avanzar(180001);
    p.ejecutar(180001);
    assert.equal(p.dichos.length, 1);
});
test('una recomendación espera a que la pestaña vuelva a estar visible y a que cierre el diálogo', () => {
    const p = iniciar('/inicio', {}, {preferencias:{rutina:'biblioteca'}});
    p.document.hidden = true;
    for (const fn of p.eventos.visibilitychange) fn();
    p.avanzar(200000);
    p.ejecutar(180001);
    assert.deepEqual(p.dichos, []);
    p.document.hidden = false;
    for (const fn of p.eventos.visibilitychange) fn();
    p.busqueda.open = true;
    p.avanzar(180001);
    p.ejecutar(180001);
    assert.deepEqual(p.dichos, []);
    p.busqueda.open = false;
    p.avanzar(15000);
    p.ejecutar(15000);
    assert.deepEqual(p.dichos, ['Sueles abrir Biblioteca. ¿Vamos?']);
});
test('Mensajería protege la edición, el envío y la posición del compositor', () => {
    const compositor = {left:0, right:390, top:510, bottom:844};
    const p = iniciar('/mensajeria', {}, {mensajeria:true, ancho:390, alto:844, protegidos:[compositor]});
    p.document.activeElement = p.texto; p.figura.click();
    p.document.activeElement = null; p.envio.activo = true; p.figura.click();
    p.envio.activo = false; p.selector.open = true; p.figura.click();
    assert.deepEqual(p.dichos, []);
    p.selector.open = false; p.figura.click();
    assert.equal(p.dichos.length, 1);
    assert.ok(parseFloat(p.figura.style.top) + 93 <= compositor.top);
});
test('el diálogo asistido y la confirmación bloquean lectura y consejos automáticos', () => {
    const p = iniciar(); const campo = new p.Entrada();
    for (const fn of p.eventos.input) fn({target:campo});
    p.busqueda.open = true; p.avanzar(3000); p.ejecutar(3000);
    assert.deepEqual(p.dichos, []);
    p.busqueda.open = false; p.confirmacion.open = true;
    for (const fn of p.eventos.input) fn({target:campo});
    p.avanzar(3000); p.ejecutar(3000); assert.deepEqual(p.dichos, []);
});
test('la lectura espera a que termine la escritura y se mantiene la ayuda solicitada', () => {
    const p = iniciar('/expedientes', {puedeGestionarExpedientes:false});
    const campo = new p.Entrada();
    for (const fn of p.eventos.input) fn({target:campo});
    p.avanzar(3000); p.ejecutar(3000); assert.deepEqual(p.dichos, ['Búsqueda: ficticio']);
    p.figura.click(); assert.match(p.dichos.at(-1), /consultar/); assert.doesNotMatch(p.dichos.at(-1), /crear|vincular/i);
});
test('las ayudas distinguen el explorador y el formulario de expedientes', () => {
    const lector = iniciar('/expedientes', {puedeGestionarExpedientes:false});
    lector.figura.click();
    assert.match(lector.dichos[0], /Abre una carpeta.*documentos visibles/);
    assert.doesNotMatch(lector.dichos[0], /Nuevo expediente|crear/i);
    const editor = iniciar('/expedientes', {puedeGestionarExpedientes:true});
    editor.figura.click(); assert.match(editor.dichos[0], /Nuevo expediente/);
    const nuevo = iniciar('/expedientes/nuevo', {puedeGestionarExpedientes:true});
    nuevo.figura.click(); assert.match(nuevo.dichos[0], /nombre o asunto.*descripción.*folio/i);
    assert.doesNotMatch(nuevo.dichos[0], /en la ficha|vincular/i);
});
test('Clippy reconoce el control Buscar y filtrar al enfocarlo', () => {
    const p = iniciar('/');
    const control = {dataset:{clippyTip:'Abre Buscar y filtrar.'}, closest:()=>null};
    const target = {matches: selector => selector.includes('summary[data-clippy-tip]'), closest:()=>control};
    for (const fn of p.eventos.focusin) fn({type:'focusin', target});
    assert.deepEqual(p.dichos, ['Abre Buscar y filtrar.']);
});
test('el consejo de Biblioteca menciona Expedientes solo si está permitido', () => {
    const conAcceso = iniciar('/', {puedeVerExpedientes:true});
    conAcceso.figura.click(); assert.match(conAcceso.dichos[0], /Buscar y filtrar.*Expedientes.*menú lateral/);
    const sinAcceso = iniciar('/', {puedeVerExpedientes:false});
    sinAcceso.figura.click(); assert.match(sinAcceso.dichos[0], /Buscar y filtrar/);
    assert.doesNotMatch(sinAcceso.dichos[0], /Expedientes/);
});
test('la posición en reposo reserva espacio al expandirse en escritorio y móvil', () => {
    for (const ancho of [1200, 390]) {
        const control = {left:ancho-160, right:ancho, top:300, bottom:500};
        const p = iniciar('/inicio', {}, {ancho, alto:800, controles:[control]});
        const {x,y} = p.movimientos.at(-1);
        assert.ok(x >= 8 && x + 124 <= ancho - 8, `posición horizontal ${ancho}`);
        assert.ok(y >= 8 && y + 93 <= 792, `posición vertical ${ancho}`);
        assert.ok(x + 124 <= control.left || x >= control.right || y + 93 <= control.top || y >= control.bottom, `sin cubrir control ${ancho}`);
        const abajo = Math.min(Math.max(16, 800 - y + 16), 640);
        const globo = {left:Math.max(12, ancho-272), right:ancho-12, top:800-abajo-Math.min(240, 800-abajo-12), bottom:800-abajo};
        assert.ok(globo.right <= control.left || globo.left >= control.right || globo.bottom <= control.top || globo.top >= control.bottom, `bocadillo libre ${ancho}`);
    }
});
test('las escalas visuales y de posicionamiento coinciden', () => {
    const css = fs.readFileSync(path.join(__dirname, '../app/static/clippy/clippy.css'), 'utf8');
    assert.match(css, /clippy-inactivo\s*\{\s*transform:\s*scale\(0\.50\)/);
    assert.match(css, /clippy-inactivo\s*\{\s*transform:\s*scale\(0\.40\)/);
    for (const [ancho, escala] of [[1200, 0.5], [390, 0.4]]) {
        const p = iniciar('/inicio', {}, {ancho, alto:800});
        const {x} = p.movimientos.at(-1);
        assert.ok(Math.abs(x + 124 - (ancho - 8)) < 0.01);
        assert.equal(124 * escala, ancho === 390 ? 49.6 : 62);
    }
});
test('Clippy permanece junto al bocadillo aunque haya controles en el lateral', () => {
    for (const ancho of [1200, 390]) {
        const control = {left:ancho-160, right:ancho, top:300, bottom:500};
        const p = iniciar('/inicio', {}, {ancho, alto:800, controles:[control]});
        const {x} = p.movimientos.at(-1);
        assert.ok(Math.abs(x + 124 - (ancho - 8)) < 0.01, `borde derecho ${ancho}`);
    }
});
test('movimiento reducido detiene animaciones de reposo', () => {
    const p = iniciar('/inicio', {}, {movimientoReducido:true});
    p.agente._onQueueEmpty(); assert.equal(p.reposos(), 0);
    const sinPreferencia = iniciar('/inicio', {}, {movimientoReducido:false});
    sinPreferencia.agente._onQueueEmpty(); assert.equal(sinPreferencia.reposos(), 1);
});
test('las reacciones siguen al mensaje y no se acumulan ante otra petición', () => {
    const p = iniciar('/inicio', {}, {movimientoReducido:false, animaciones:['Wave']});
    p.figura.click(); p.figura.click();
    assert.equal(p.colaAnimaciones.length, 1);
    assert.equal(p.dichos.length, 2);
    p.colaAnimaciones.shift()(() => {});
    assert.deepEqual(p.reacciones, ['Wave']);
});
test('la reacción pendiente se omite si cambia movimiento reducido o hay un diálogo', () => {
    for (const bloquear of [p => {p.movimiento.matches = true;}, p => {p.busqueda.open = true;}]) {
        const p = iniciar('/inicio', {}, {movimientoReducido:false, animaciones:['Wave']});
        p.figura.click(); bloquear(p); let continuada = false;
        p.colaAnimaciones.shift()(() => {continuada = true;});
        assert.equal(continuada, true); assert.deepEqual(p.reacciones, []);
    }
});
test('una reacción caducada no se reproduce', () => {
    const p = iniciar('/inicio', {}, {movimientoReducido:false, animaciones:['Wave']});
    p.figura.click(); p.avanzar(15001); let continuada = false;
    p.colaAnimaciones.shift()(() => {continuada = true;});
    assert.equal(continuada, true); assert.deepEqual(p.reacciones, []);
});
test('saludo y gesto nuevo no reproducen sonidos', () => {
    const p = iniciar();
    for (const nombre of ['Greeting', 'Wave', 'Congratulate']) {
        p.agente._animator.currentAnimationName = nombre;
        p.agente._animator._playSound();
    }
    assert.deepEqual(p.sonidos, ['sonido']);
});
test('sin resultados usa una reacción discreta y conserva el mensaje', () => {
    const p = iniciar('/', {bibliotecaSinResultados:true}, {movimientoReducido:false, animaciones:['LookLeft']});
    p.figura.click(); assert.match(p.dichos[0], /no encontró/);
    p.colaAnimaciones.shift()(() => {}); assert.deepEqual(p.reacciones, ['LookLeft']);
});
test('un resultado exitoso usa la reacción de confirmación', () => {
    const p = iniciar('/inicio', {}, {movimientoReducido:false, animaciones:['Congratulate'], search:'?aviso=subido'});
    p.figura.click(); assert.match(p.dichos[0], /Documento subido/);
    p.colaAnimaciones.shift()(() => {}); assert.deepEqual(p.reacciones, ['Congratulate']);
});
