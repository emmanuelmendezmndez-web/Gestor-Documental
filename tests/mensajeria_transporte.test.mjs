import test from "node:test";
import assert from "node:assert/strict";
import {
    buscarDocumentos, caracteres, enviar, mensajeError, plazoPeticion, referencia, textoValido,
} from "../app/static/mensajeria_transporte.mjs";

const ref = "a".repeat(32);
const csrf = "csrf-ficticio";
const cabecera = { querySelector: () => ({ content: csrf }) };

test("el plazo de una petición distingue vencimiento, cancelación y finalización", t => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const origen = new AbortController();
    const cancelada = plazoPeticion(20, origen.signal);
    origen.abort();
    assert.equal(cancelada.signal.reason.name, "AbortError");
    assert.equal(plazoPeticion(20, origen.signal).signal.aborted, true);

    const origenFinalizado = new AbortController();
    const finalizada = plazoPeticion(20, origenFinalizado.signal);
    finalizada.liberar();
    origenFinalizado.abort();
    const vencida = plazoPeticion(20);
    t.mock.timers.tick(20);
    assert.equal(finalizada.signal.aborted, false);
    assert.equal(vencida.signal.reason.name, "TimeoutError");
});

test("cuenta puntos de código y limita mensajes de texto plano", () => {
    assert.equal(caracteres("A🙂🎉e\u0301"), 5);
    assert.equal(textoValido("🙂".repeat(300)), true);
    assert.equal(textoValido("🙂".repeat(301)), false);
    assert.equal(textoValido(" \n"), false);
    assert.equal(textoValido("x\0"), false);
    assert.equal(textoValido("<img src=x onerror=alert(1)>"), true);
    assert.equal(referencia("../ajeno"), false);
});

test("reintenta la confirmación externa sin repetir la carga ni cambiar su identidad", async t => {
    t.mock.method(globalThis, "fetch", async (ruta, opciones) => {
        assert.equal(ruta, "/mensajeria/api/v1/envios/externos/confirmar");
        assert.equal(opciones.credentials, "same-origin");
        assert.equal(opciones.headers["X-CSRF-Token"], csrf);
        if (intentos.length === 1) {
            intentos.push(opciones.body);
            return new Response(JSON.stringify({ mensaje: ref }));
        }
        intentos.push(opciones.body);
        throw new TypeError("Corte simulado");
    });
    globalThis.document = cabecera;
    t.after(() => { delete globalThis.document; });
    const intentos = [];
    const operacion = {
        destinatario: ref, texto: "Ficticio 🙂", clave: "b".repeat(32),
        adjunto: { archivo: new Blob(["ficticio"]) }, preparado: { nombre: "ficticio.txt", tamano_bytes: 8 },
    };
    const etapas = [];
    const actualizar = estado => etapas.push(estado);
    await assert.rejects(enviar(operacion, actualizar), error => error.resultadoIncierto === true);
    assert.equal(await enviar(operacion, actualizar), ref);
    assert.equal(intentos[0], intentos[1]);
    assert.deepEqual(etapas, ["Confirmando envío…", "Confirmando envío…"]);
});

test("envía referencias internas con la modalidad seleccionada y traduce el error de cuota", async t => {
    globalThis.document = cabecera;
    t.after(() => { delete globalThis.document; });
    t.mock.method(globalThis, "fetch", async (ruta, opciones) => {
        assert.equal(ruta, "/mensajeria/api/v1/envios/biblioteca");
        assert.deepEqual(JSON.parse(opciones.body), {
            destinatario: ref, clave: ref, texto: "Ficticio",
            documento: ref, modalidad: "visualizar",
        });
        return new Response('{"error":"cuota_agotada"}', { status: 429 });
    });
    const operacion = {
        destinatario: ref, texto: "Ficticio", clave: ref,
        adjunto: { referencia: ref, modalidad: "visualizar" },
    };
    await assert.rejects(enviar(operacion, () => {}), error =>
        error.estado === 429 && !error.resultadoIncierto && mensajeError(error).includes("50 envíos"));
});

test("la selección de Biblioteca entrega un nombre y una referencia, sin un archivo local", async t => {
    globalThis.DOMParser = class {
        parseFromString() {
            const texto = { strong: "Circular <ficticia>", span: "Circular.txt" };
            return {
                getElementById: () => ({
                    children: [{
                        dataset: { referencia: ref, soloVista: "si" },
                        querySelector: selector => ({ textContent: texto[selector] }),
                    }],
                    dataset: { descarga: "si", siguiente: "" },
                }),
            };
        }
    };
    t.after(() => { delete globalThis.DOMParser; });
    t.mock.method(globalThis, "fetch", async (ruta, opciones) => {
        assert.equal(ruta, "/mensajeria?destinatario=" + ref);
        assert.equal(opciones.credentials, "same-origin");
        return new Response("<ul></ul>");
    });
    const datos = await buscarDocumentos(new URLSearchParams({ destinatario: ref }));
    assert.deepEqual(datos.elementos, [{
        referencia: ref, nombre: "Circular <ficticia>", nombreArchivo: "Circular.txt", soloVista: true,
    }]);
});
