const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function iniciar({reducido = false, closeDiferido = false} = {}) {
    const timers = new Map(), eventos = {}, controles = {}, clases = new Set();
    let secuencia = 0;
    const elemento = () => ({dataset:{}, hidden:false, value:'', classList:{add(){}, remove(){}, toggle(){}},
        replaceChildren(...hijos){this.hijos = hijos; this.textContent = hijos.map(h => h.textContent).join('');},
        addEventListener(nombre, fn){this[nombre] = fn;}, setCustomValidity(){}, focus(){}, reportValidity(){}});
    const confirmar = elemento(), cancelar = elemento(), clave = elemento(), contenedor = elemento();
    clave.setCustomValidity = valor => { clave.error = valor; };
    const dialogo = {open:false, dataset:{}, classList:{add:n => clases.add(n), remove:n => clases.delete(n)},
        querySelector(q){return q.includes('confirmar') ? confirmar : cancelar;},
        addEventListener(n, fn){eventos[n] = fn;}, removeEventListener(n){delete eventos[n];},
        showModal(){this.open = true;}, close(){this.open = false; if (!closeDiferido) eventos.close?.();}};
    Object.assign(controles, {'dialogo-confirmacion':dialogo, 'dialogo-confirmacion-titulo':elemento(),
        'dialogo-confirmacion-mensaje':elemento(), 'dialogo-clave-confirmacion':contenedor,
        'dialogo-confirmacion-password':clave, 'dialogo-confirmacion-afectado':elemento(),
        'dialogo-confirmacion-afectado-nombre':elemento(), 'dialogo-confirmacion-afectado-icono':elemento()});
    const document = {getElementById:id => controles[id], addEventListener(n, fn){eventos['documento_'+n] = fn;},
        querySelectorAll:()=>[], createElement:()=>elemento(), createTextNode:valor=>({textContent:valor})};
    const window = {matchMedia:()=>({matches:reducido}), requestAnimationFrame:fn => fn(),
        setTimeout(fn){const id = ++secuencia; timers.set(id,fn); return id;}, clearTimeout:id => timers.delete(id)};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../app/static/dialogos.js'), 'utf8'), {window, document, HTMLInputElement:class {}});
    let envios = 0;
    const formulario = {dataset:{confirm:'¿Continuar?'}, elements:[], hasAttribute:n => n === 'data-confirm', getAttribute:n => n === 'action' ? formulario.action || '' : null,
        querySelector(selector){return selector === 'template[data-confirm-file-icon]' ? this.plantilla || null : this.oculto || null;}, append(el){this.oculto = el;},
        requestSubmit(){envios++; const e = {target:formulario, preventDefault(){throw Error('confirmación repetida');}}; eventos.documento_submit(e);}};
    function abrir(submitter) { let prevenido = false; eventos.documento_submit({target:formulario, submitter, preventDefault(){prevenido = true;}}); assert.ok(prevenido); }
    return {dialogo, confirmar, cancelar, clave, eventos, timers, clases, formulario, controles, abrir, envios:()=>envios};
}

test('cancelar y Escape cierran sin enviar y sin duplicar cierres', () => {
    for (const escape of [false, true]) {
        const p = iniciar(); p.abrir();
        if (escape) { let prevenido = false; p.eventos.cancel({preventDefault(){prevenido = true;}}); assert.ok(prevenido); }
        else p.cancelar.click();
        assert.equal(p.dialogo.open, true); assert.equal(p.envios(), 0);
        p.eventos.animationend({target:p.dialogo});
        assert.equal(p.dialogo.open, false); assert.equal(p.envios(), 0); assert.equal(p.timers.size, 0);
    }
});

test('confirmar envía inmediatamente una sola vez y no espera la animación', () => {
    const p = iniciar(); p.abrir(); p.confirmar.click(); p.confirmar.click();
    assert.equal(p.envios(), 1); assert.equal(p.dialogo.open, false); assert.equal(p.timers.size, 0);
});

test('movimiento reducido cierra inmediatamente y permite volver a abrir', () => {
    const p = iniciar({reducido:true}); p.abrir(); p.cancelar.click();
    assert.equal(p.dialogo.open, false); assert.equal(p.timers.size, 0);
    p.abrir(); assert.equal(p.dialogo.open, true);
});

test('confirmar durante un cierre cancelado no envía la operación', () => {
    const p = iniciar(); p.abrir(); p.cancelar.click(); p.confirmar.click();
    assert.equal(p.envios(), 0); p.eventos.animationend({target:p.dialogo});
    assert.equal(p.dialogo.open, false);
});

test('una confirmación que exige contraseña valida antes de enviar', () => {
    const p = iniciar(); p.formulario.dataset.confirmPassword = 'true'; p.abrir();
    p.confirmar.click(); assert.equal(p.envios(), 0); assert.match(p.clave.error, /contraseña/);
    p.clave.value = 'clave ficticia'; p.confirmar.click();
    assert.equal(p.envios(), 1); assert.equal(p.formulario.oculto.value, 'clave ficticia');
    assert.equal(p.clave.value, '');
});

test('un close diferido no borra una nueva confirmación', () => {
    const p = iniciar({closeDiferido:true}); p.abrir(); p.cancelar.click();
    p.eventos.animationend({target:p.dialogo}); p.abrir();
    p.eventos.close(); assert.equal(p.dialogo.open, true);
    p.confirmar.click(); assert.equal(p.envios(), 1);
});

test('la presentación distingue la operación y conserva el mensaje como texto', () => {
    for (const [ruta, icono, tono] of [['/documentos/1/eliminar','enviar-papelera','aviso'], ['/papelera/restaurar','restaurar','aviso'], ['/expedientes/2/eliminar','expediente','peligro'], ['/papelera/vaciar','papelera','peligro'], ['/usuarios/3/eliminar','usuario','peligro'], ['/usuarios/3/estado','usuario','peligro'], ['/avisos/4/eliminar','comunicado','peligro']]) {
        const p = iniciar(); p.formulario.action = ruta; p.formulario.dataset.confirmTone = 'danger';
        const texto = 'Eliminar «<nombre ficticio>» sin modificar el mensaje.';
        p.formulario.dataset.confirm = texto; p.abrir();
        assert.equal(p.dialogo.dataset.icono, icono); assert.equal(p.dialogo.dataset.tono, tono);
        const mensaje = p.controles['dialogo-confirmacion-mensaje'];
        assert.equal(mensaje.textContent, texto); assert.equal(mensaje.hijos[1].textContent, '«<nombre ficticio>»');
        assert.equal(p.controles['dialogo-confirmacion-afectado'].hidden, false);
        assert.equal(p.controles['dialogo-confirmacion-afectado-nombre'].textContent, '<nombre ficticio>');
        assert.equal(p.envios(), 0);
    }
});

test('la descripción independiente evita repetir el nombre y conserva texto seguro', () => {
    const p = iniciar(); p.formulario.action = '/documentos/1/eliminar';
    p.formulario.dataset.confirm = '«<documento ficticio>» dejará de aparecer.';
    p.formulario.dataset.confirmDescription = 'El documento dejará de aparecer en la biblioteca.';
    p.abrir();
    assert.equal(p.controles['dialogo-confirmacion-mensaje'].textContent, 'El documento dejará de aparecer en la biblioteca.');
    assert.equal(p.controles['dialogo-confirmacion-afectado-nombre'].textContent, '<documento ficticio>');
    assert.equal(p.envios(), 0);
});

test('la presentación sin datos de operación conserva un aviso seguro', () => {
    const p = iniciar(); p.abrir();
    assert.equal(p.dialogo.dataset.icono, 'aviso'); assert.equal(p.dialogo.dataset.tono, 'normal');
    assert.equal(p.controles['dialogo-confirmacion-mensaje'].textContent, '¿Continuar?');
    assert.equal(p.controles['dialogo-confirmacion-afectado'].hidden, true);
});

test('el icono sigue el destino formaction del botón que envía', () => {
    const p = iniciar(); p.formulario.action = '/documentos/papelera';
    const boton = {hasAttribute:()=>false, getAttribute:n => n === 'formaction' ? '/papelera/eliminar-seleccionados' : null};
    p.abrir(boton); assert.equal(p.dialogo.dataset.icono, 'papelera');
});

test('utiliza el icono asociado al archivo y lo limpia en la siguiente confirmación', () => {
    const p = iniciar();
    p.formulario.dataset.confirm = 'Enviar «Documento ficticio» a la papelera.';
    p.formulario.plantilla = {content:{cloneNode:()=>({textContent:'SVG DOCX ficticio'})}};
    p.abrir();
    assert.equal(p.controles['dialogo-confirmacion-afectado-icono'].textContent, 'SVG DOCX ficticio');
    p.cancelar.click(); p.eventos.animationend({target:p.dialogo});
    p.formulario.plantilla = null;
    p.abrir();
    assert.equal(p.controles['dialogo-confirmacion-afectado-icono'].textContent, '');
});

test('muestra la carpeta del expediente sin enviar la operación', () => {
    const p = iniciar();
    p.formulario.action = '/expedientes/1/eliminar';
    p.formulario.dataset.confirm = 'Eliminar «EXP-001 — Expediente ficticio».';
    p.formulario.plantilla = {content:{cloneNode:()=>({textContent:'carpeta ficticia'})}};
    p.abrir();
    assert.equal(p.controles['dialogo-confirmacion-afectado-icono'].textContent, 'carpeta ficticia');
    assert.equal(p.controles['dialogo-confirmacion-afectado-nombre'].textContent, 'EXP-001 — Expediente ficticio');
    assert.equal(p.envios(), 0);
});

test('la confirmación administrativa y los nombres explícitos no cambian la operación', () => {
    const p = iniciar(); p.formulario.action = '/usuarios/3/estado';
    p.formulario.dataset.confirmSubject = 'María <ficticia>';
    p.formulario.dataset.confirmPassword = 'true'; p.abrir();
    assert.equal(p.dialogo.dataset.icono, 'administracion');
    assert.equal(p.controles['dialogo-confirmacion-afectado-nombre'].textContent, 'María <ficticia>');
    assert.equal(p.controles['dialogo-confirmacion-mensaje'].textContent, '¿Continuar?');
    assert.equal(p.envios(), 0);
});
