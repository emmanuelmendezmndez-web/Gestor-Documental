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
    class Entrada { constructor(){ this.type='text'; this.value='ficticio'; this.dataset={clippyRead:'Búsqueda'}; } hasAttribute(){return true;} closest(){return null;} }
    const document = {readyState:'complete', addEventListener(tipo, fn){ (eventos[tipo] ||= []).push(fn); },
        getElementById(id){return id === 'busqueda-asistida' ? busqueda : id === 'dialogo-confirmacion' ? confirmacion : null;},
        querySelector(q){return q === '.clippy' ? figura : null;}, querySelectorAll(){return (opciones.controles || []).map(rect => ({getClientRects:()=>[rect], getBoundingClientRect:()=>rect}));}};
    const agente = {_getIdleAnimation(){}, hasAnimation(nombre){return (opciones.animaciones || []).includes(nombre);}, _onQueueEmpty(){reposos++;}, _queue:{}, _balloon:{hide(){}, _balloon:{hide(){}}}, _animator:{_playSound(){sonidos.push('sonido');}},
        _addToQueue(fn){colaAnimaciones.push(fn);}, _playInternal(nombre, fin){reacciones.push(nombre); fin(nombre, 'exited');},
        speak(texto){dichos.push(texto);}, stop(){colaAnimaciones.length=0;}, moveTo(x,y){movimientos.push({x,y}); figura.style.top = String(y);}, show(){}};
    const window = {clippy:true, sigedClippyConfig:{basePath:'', usuarioId:1, nombre:'Prueba', ...config}, location:{pathname:ruta, search:opciones.search || ''},
        innerHeight:opciones.alto || 800, innerWidth:opciones.ancho || 1200, matchMedia:()=>movimiento, requestAnimationFrame(){}, addEventListener(){}, removeEventListener(){},
        setTimeout(fn, ms){const id=++secuencia; timers.set(id,{fn, ms}); return id;}, clearTimeout(id){timers.delete(id);}};
    class Fecha extends Date { static now(){return reloj;} }
    const ctx = {window, document, clippy:{Animator:{States:{EXITED:'exited'}}, load(_nombre, fn){fn(agente);}}, Date:Fecha, URLSearchParams, HTMLElement:Entrada, HTMLInputElement:Entrada, getComputedStyle:()=>({display:'none'}), console};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../app/static/clippy_asistente.js'), 'utf8'), ctx);
    return {busqueda, confirmacion, figura, dichos, eventos, Entrada, timers, movimientos, agente, reacciones, colaAnimaciones, movimiento, sonidos, reposos:()=>reposos, avanzar(ms){reloj += ms;}, ejecutar(ms){const lista=[...timers.entries()].filter(([, t])=>t.ms===ms); for (const [id,t] of lista) {timers.delete(id); t.fn();}}};
}
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
