import assert from "node:assert/strict";
import { test } from "node:test";

class Nodo extends EventTarget {
    dataset = {};
    style = { setProperty() {}, removeProperty() {} };
    value = "";
    get parentElement() { return this; }

    querySelector(selector) { return selector.includes("almacenamiento") ? null : this; }
    querySelectorAll() { return []; }
    closest() { return this; }
    toggleAttribute() {}
    setAttribute() {}
    removeAttribute() {}
}

test("Mensajería móvil carga la bandeja sin Volver a Inicio ni las API estáticas de AbortSignal", async t => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const nodos = new Map();
    const nodo = id => {
        if (!nodos.has(id)) nodos.set(id, new Nodo());
        return nodos.get(id);
    };
    const window = new EventTarget();
    const document = Object.assign(new EventTarget(), {
        getElementById: id => id === "mensajeria-inicio" ? null : nodo(id),
        querySelector: nodo,
    });
    const navegador = {
        document, window, location: { search: "" },
        matchMedia: () => Object.assign(new EventTarget(), { matches: true }),
        IntersectionObserver: class {},
    };
    for (const [nombre, valor] of Object.entries(navegador)) {
        const previo = Object.getOwnPropertyDescriptor(globalThis, nombre);
        Object.defineProperty(globalThis, nombre, { configurable: true, value: valor });
        t.after(() => {
            if (previo) Object.defineProperty(globalThis, nombre, previo);
            else delete globalThis[nombre];
        });
    }
    for (const metodo of ["any", "timeout"]) {
        const previo = Object.getOwnPropertyDescriptor(AbortSignal, metodo);
        delete AbortSignal[metodo];
        if (previo) t.after(() => Object.defineProperty(AbortSignal, metodo, previo));
    }
    const peticiones = [];
    t.mock.method(globalThis, "fetch", async (ruta, { signal }) => {
        peticiones.push(ruta);
        assert.equal(signal.aborted, false);
        return {
            ok: true,
            json: async () => ({ conversaciones: { elementos: [] }, no_leidos: 0, cuota: { restantes: 50, limite: 50 } }),
        };
    });

    await import("../app/static/mensajeria.js");
    t.after(() => window.dispatchEvent(new Event("pagehide")));
    t.mock.timers.tick(60);
    await new Promise(resolve => setImmediate(resolve));

    assert.deepEqual(peticiones, ["/mensajeria/api/v1/sincronizacion?archivadas=false&avisos=true"]);
    assert.match(nodo("mensajeria-estado-lista").textContent, /Aún no tienes conversaciones/);
    assert.equal(nodo("mensajeria-reintentar-lista").hidden, true);
});
