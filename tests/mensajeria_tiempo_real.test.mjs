import assert from "node:assert/strict";
import { test } from "node:test";
import { conectarMensajeria } from "../app/static/mensajeria_tiempo_real.mjs";

const token = n => String(n).padStart(32, "0") + "." + "a".repeat(64);

function navegador(t, actualizar, ruta = "/mensajeria/ws") {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    t.mock.method(Math, "random", () => 0.5);
    const sockets = [];
    const errores = [];
    const cierres = [];
    const window = new EventTarget();
    const document = new EventTarget();
    const navigator = { onLine: true };
    const location = { origin: "https://siged.ejemplo:8443" };
    class WebSocket extends EventTarget {
        constructor(url) {
            super();
            this.url = url.href;
            this.enviados = [];
            sockets.push(this);
        }
        send(texto) { this.enviados.push(JSON.parse(texto)); }
        close() { this.cerrado = true; }
        caer(code) { this.dispatchEvent(Object.assign(new Event("close"), { code })); }
        emitir(tipo, cursor) {
            this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({ tipo, cursor }) }));
        }
    }
    for (const [nombre, valor] of Object.entries({ window, document, navigator, location, WebSocket })) {
        const previo = Object.getOwnPropertyDescriptor(globalThis, nombre);
        Object.defineProperty(globalThis, nombre, { configurable: true, value: valor });
        t.after(() => {
            if (previo) Object.defineProperty(globalThis, nombre, previo);
            else delete globalThis[nombre];
        });
    }
    const canal = conectarMensajeria({
        ruta, actualizar, cerrarSesion: error => cierres.push(error), informar: error => errores.push(error),
    });
    t.after(canal.detener);
    const pasar = async ms => {
        t.mock.timers.tick(ms);
        await Promise.resolve();
        await Promise.resolve();
    };
    return { sockets, errores, cierres, pasar, window, document, navigator };
}

test("agrupa señales y conserva pendientes que llegan durante HTTP", async t => {
    const solicitudes = [];
    const resoluciones = [];
    const { sockets, pasar } = navegador(t, datos => {
        solicitudes.push(datos);
        return new Promise(resolve => resoluciones.push(resolve));
    });
    const [primero] = sockets;
    assert.equal(primero.url, "wss://siged.ejemplo:8443/mensajeria/ws");
    primero.emitir("conexion_lista");
    primero.emitir("conexion_lista");
    assert.deepEqual(primero.enviados, [{ tipo: "sincronizar", cursor: null }]);
    primero.emitir("resincronizar", token(1));
    await pasar(60);
    primero.emitir("mensaje_nuevo", token(3));
    primero.emitir("mensaje_nuevo", token(2));
    primero.emitir("mensaje_nuevo", token(3));
    primero.emitir("mensaje_nuevo", "cursor inválido");
    await pasar(60);
    assert.equal(solicitudes.length, 1);
    resoluciones.shift()();
    await pasar(0);
    await pasar(60);
    assert.equal(solicitudes.length, 2);
    assert.equal(solicitudes[1].nuevo, true);
    resoluciones.shift()();
    await pasar(0);
    primero.emitir("mensaje_nuevo", token(3));
    await pasar(60);
    assert.equal(solicitudes.length, 2);
});

test("reconecta desde el cursor aplicado si cae el servidor o falla HTTP", async t => {
    let fallo = false;
    const { sockets, pasar, errores } = navegador(t, async () => {
        if (fallo) throw new Error("sin conexión");
    });
    sockets[0].emitir("conexion_lista");
    sockets[0].emitir("resincronizar", token(1));
    await pasar(60);
    fallo = true;
    sockets[0].emitir("mensaje_nuevo", token(2));
    sockets[0].caer(1006);
    await pasar(60);
    assert.equal(errores.length, 1);
    await pasar(940);
    sockets[1].emitir("conexion_lista");
    assert.deepEqual(sockets[1].enviados, [{ tipo: "sincronizar", cursor: token(1) }]);
    fallo = false;
    sockets[1].emitir("mensaje_nuevo", token(2));
    await pasar(60);
    sockets[1].caer(1012);
    await pasar(1000);
    sockets[2].emitir("conexion_lista");
    assert.deepEqual(sockets[2].enviados, [{ tipo: "sincronizar", cursor: token(2) }]);
});

test("recupera tras desconexión y suspensión y se detiene al revocar la sesión", async t => {
    const { sockets, pasar, cierres, window, navigator } = navegador(t, async () => {});
    sockets[0].emitir("conexion_lista");
    sockets[0].emitir("resincronizar", null);
    await pasar(60);
    navigator.onLine = false;
    window.dispatchEvent(new Event("offline"));
    await pasar(1000);
    assert.equal(sockets.length, 1);
    navigator.onLine = true;
    window.dispatchEvent(new Event("online"));
    assert.equal(sockets.length, 2);
    window.dispatchEvent(new Event("pagehide"));
    assert.equal(sockets[1].cerrado, true);
    window.dispatchEvent(new Event("pageshow"));
    sockets[2].emitir("conexion_lista");
    sockets[2].caer(1008);
    await pasar(30000);
    assert.equal(cierres[0].estado, 401);
    assert.equal(sockets.length, 3);
});

test("detiene los reintentos si HTTP confirma que la sesión expiró", async t => {
    const { sockets, pasar, cierres } = navegador(t, async () => {
        throw Object.assign(new Error(), { estado: 401 });
    });
    sockets[0].caer(1006);
    await pasar(60);
    await pasar(30000);
    assert.equal(cierres[0].estado, 401);
    assert.equal(sockets.length, 1);
});

test("reconstruye desde el ancla que devuelve el servidor y descarta el canal anterior", async t => {
    const consultas = [];
    const { sockets, pasar } = navegador(t, async datos => { consultas.push(datos); });
    const [anterior] = sockets;
    anterior.emitir("conexion_lista");
    anterior.emitir("resincronizar", token(1));
    await pasar(60);
    anterior.caer(1006);
    await pasar(1000);
    sockets[1].emitir("conexion_lista");
    assert.equal(sockets[1].enviados[0].cursor, token(1));
    sockets[1].emitir("resincronizar", null);
    anterior.emitir("mensaje_nuevo", token(2));
    await pasar(60);
    assert.equal(consultas.at(-1).completo, true);
    assert.equal(consultas.at(-1).nuevo, false);
    sockets[1].caer(1006);
    await pasar(1000);
    sockets[2].emitir("conexion_lista");
    assert.equal(sockets[2].enviados[0].cursor, null);
});

test("conserva la señal si el cambio de conversación interrumpe su aplicación", async t => {
    const consultas = [];
    const { sockets, pasar } = navegador(t, async datos => {
        consultas.push(datos);
        return consultas.length !== 2;
    });
    sockets[0].emitir("conexion_lista");
    sockets[0].emitir("resincronizar", token(1));
    await pasar(60);
    sockets[0].emitir("mensaje_nuevo", token(2));
    await pasar(60);
    assert.equal(consultas.length, 2);
    sockets[0].caer(1006);
    await pasar(60);
    await pasar(940);
    sockets[1].emitir("conexion_lista");
    assert.equal(sockets[1].enviados[0].cursor, token(2));
    assert.equal(consultas[2].nuevo, true);
});

test("sin montaje WebSocket conserva la consulta HTTP sin abrir el canal", async t => {
    let consultas = 0;
    const { sockets, pasar } = navegador(t, async () => { consultas++; }, null);
    await pasar(60);
    assert.equal(consultas, 1);
    assert.equal(sockets.length, 0);
});
