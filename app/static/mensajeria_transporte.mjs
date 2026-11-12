export const API = "/mensajeria/api/v1";
export const LIMITE = 20 * 1024 * 1024;
export const referencia = valor => typeof valor === "string" && /^[0-9a-f]{32}$/.test(valor);
export const caracteres = texto => Array.from(texto).length;
export const textoValido = texto => Boolean(texto.trim()) && caracteres(texto) <= 300 && !texto.includes("\0");
export const formato = nombre => nombre.split(".").pop().toLowerCase();
export const claveEnvio = () => Array.from(crypto.getRandomValues(new Uint8Array(16)),
    byte => byte.toString(16).padStart(2, "0")).join("");

export class ErrorHTTP extends Error {
    constructor(estado, codigo) {
        super(codigo || "servicio_no_disponible");
        this.estado = estado;
    }
}

export function mensajeError(error) {
    const codigos = {
        identidad_no_reconciliada: "Mensajería está en pausa. Solicita al administrador que reconcilie la restauración.",
        generacion_cambio: "Los datos cambiaron durante la operación. Vuelve a iniciar sesión cuando Mensajería esté disponible.",
        cuota_agotada: "Agotaste la cuota diaria de 50 envíos.",
        conflicto_idempotencia: "La operación ya existe con otros datos. Revisa el historial antes de iniciar otro envío.",
        formato_no_permitido: "Este formato de archivo no está permitido.",
        formato_incompatible: "El contenido del archivo no coincide con su formato.",
        nombre_invalido: "Cambia el nombre del archivo e inténtalo nuevamente.",
        archivo_vacio: "Selecciona un archivo con contenido.",
        espacio_adjuntos_insuficiente: "No hay espacio suficiente para preparar el archivo.",
        preparacion_vencida: "La preparación del archivo venció. Vuelve a seleccionar el archivo.",
        carga_interrumpida: "Se interrumpió la carga. Puedes intentarlo nuevamente.",
    };
    if (Object.prototype.hasOwnProperty.call(codigos, error.message)) return codigos[error.message];
    return {
        0: "Se interrumpió la conexión. Comprueba tu acceso a NexusGrid.",
        400: "Revisa los datos y el archivo antes de reintentar.",
        401: "La sesión de Mensajería dejó de ser válida. Cierra sesión y vuelve a entrar.",
        403: "NexusGrid rechazó la solicitud. Actualiza la página antes de reintentar.",
        404: "El elemento ya no está disponible o no tienes acceso.",
        408: "El servidor agotó el tiempo de espera. Puedes reintentar la misma operación.",
        413: "El archivo o la solicitud supera el límite permitido de 20 MiB por archivo.",
        415: "NexusGrid rechazó el formato del archivo.",
        429: "El servidor está ocupado. Espera un momento y reintenta.",
    }[error.estado] || "Mensajería está temporalmente no disponible. Inténtalo de nuevo.";
}

const csrf = () => document.querySelector('meta[name="csrf-token"]').content;

export function plazoPeticion(milisegundos, ...origenes) {
    const control = new AbortController();
    const senales = origenes.filter(Boolean);
    const temporizador = setTimeout(() => {
        control.abort(new DOMException("Se agotó el plazo de la petición.", "TimeoutError"));
        liberar();
    }, milisegundos);

    function liberar() {
        clearTimeout(temporizador);
        for (const origen of senales) origen.removeEventListener("abort", cancelar);
    }

    function cancelar() {
        control.abort();
        liberar();
    }

    if (senales.some(origen => origen.aborted)) cancelar();
    else for (const origen of senales) origen.addEventListener("abort", cancelar, { once: true });
    return { signal: control.signal, liberar };
}

async function respuesta(ruta, opciones) {
    let resultado;
    try {
        resultado = await fetch(ruta, {
            credentials: "same-origin", cache: "no-store", redirect: "manual", ...opciones,
        });
    } catch (error) {
        if (error.name === "AbortError") throw error;
        throw new ErrorHTTP(0);
    }
    if (resultado.type === "opaqueredirect") throw new ErrorHTTP(401);
    if (!resultado.ok) {
        const datos = await resultado.json().catch(() => null);
        throw new ErrorHTTP(resultado.status, datos?.error);
    }
    return resultado;
}

export async function pedir(ruta, { datos, post = false, signal, plazo } = {}) {
    const opciones = {};
    if (post) {
        opciones.method = "POST";
        opciones.headers = { "X-CSRF-Token": csrf() };
        if (datos !== undefined) {
            opciones.headers["Content-Type"] = "application/json";
            opciones.body = JSON.stringify(datos);
        }
    }
    const limite = plazo === undefined ? null : plazoPeticion(plazo, signal);
    opciones.signal = limite?.signal ?? signal;
    try {
        const resultado = await respuesta(API + ruta, opciones);
        try {
            return await resultado.json();
        } catch (error) {
            if (error.name === "AbortError") throw error;
            throw new ErrorHTTP(0);
        }
    } finally {
        limite?.liberar();
    }
}

export async function buscarDocumentos(parametros, signal) {
    const resultado = await respuesta("/mensajeria?" + parametros, { signal });
    const pagina = new DOMParser().parseFromString(await resultado.text(), "text/html");
    const lista = pagina.getElementById("mensajeria-documentos");
    if (!lista) throw new ErrorHTTP(503);
    return {
        elementos: [...lista.children].filter(item => referencia(item.dataset.referencia)).map(item => ({
            referencia: item.dataset.referencia,
            nombre: item.querySelector("strong").textContent,
            nombreArchivo: item.querySelector("span").textContent,
            soloVista: item.dataset.soloVista === "si",
        })),
        siguiente: lista.dataset.siguiente,
        descarga: lista.dataset.descarga === "si",
    };
}

export function preparar(operacion, actualizar) {
    return new Promise((resolver, rechazar) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", API + "/envios/externos/preparar");
        xhr.timeout = 200000;
        xhr.setRequestHeader("X-CSRF-Token", csrf());
        xhr.setRequestHeader("X-SIGED-Destinatario", operacion.destinatario);
        xhr.setRequestHeader("Idempotency-Key", operacion.clave);
        xhr.upload.addEventListener("progress", evento => {
            if (evento.lengthComputable) actualizar(evento.loaded / evento.total * 100);
        });
        xhr.upload.addEventListener("load", () => actualizar(null));
        xhr.addEventListener("load", () => {
            let datos;
            try { datos = JSON.parse(xhr.responseText); } catch { /* El proxy también puede responder con texto. */ }
            if (xhr.status === 200 && typeof datos?.nombre === "string" &&
                datos.tamano_bytes === operacion.adjunto.archivo.size && datos.clave === operacion.clave) {
                resolver(datos);
            } else {
                rechazar(new ErrorHTTP(xhr.status === 200 ? 0 : xhr.status, datos?.error));
            }
        });
        for (const evento of ["error", "abort", "timeout"]) {
            xhr.addEventListener(evento, () => rechazar(new ErrorHTTP(0)));
        }
        const multipart = new FormData();
        multipart.append("archivo", operacion.adjunto.archivo);
        xhr.send(multipart);
    });
}

export async function enviar(operacion, actualizar) {
    const { destinatario, texto, clave, adjunto } = operacion;
    const datos = { destinatario, texto, clave };
    let ruta = "/envios/biblioteca";
    if (adjunto.archivo) {
        if (!operacion.preparado) {
            actualizar("Subiendo archivo…", 0);
            operacion.preparado = await preparar(operacion, avance => actualizar(
                avance === null ? "Validando el archivo en NexusGrid…" : "Subiendo archivo…", avance,
            ));
        }
        const preparado = operacion.preparado;
        Object.assign(datos, { nombre: preparado.nombre, tamano_bytes: preparado.tamano_bytes });
        ruta = "/envios/externos/confirmar";
    } else {
        Object.assign(datos, { documento: adjunto.referencia, modalidad: adjunto.modalidad ?? "visualizar_y_descargar" });
    }
    actualizar("Confirmando envío…", null);
    try {
        const resultado = await pedir(ruta, { post: true, datos, plazo: 60000 });
        if (!referencia(resultado?.mensaje)) throw new ErrorHTTP(0);
        return resultado.mensaje;
    } catch (error) {
        // Este envío solo se cancela por su plazo local. La respuesta pudo perderse después de confirmar.
        if (error.name === "AbortError") error = new ErrorHTTP(0);
        if (error.estado === 0 || error.estado >= 500) error.resultadoIncierto = true;
        throw error;
    }
}
