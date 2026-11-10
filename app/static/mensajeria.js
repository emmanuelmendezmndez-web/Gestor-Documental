import {
    API, LIMITE, buscarDocumentos, caracteres, enviar, formato, mensajeError, pedir, referencia, textoValido,
} from "./mensajeria_transporte.mjs";

const porId = id => document.getElementById(id);
const raiz = porId("mensajeria");
const campana = porId("mensajeria-campana");
const indicador = document.querySelector("[data-mensajeria-no-leidos]");
const numero = n => n > 99 ? "99+" : String(n);

function mostrarContador(total) {
    indicador.hidden = !total;
    indicador.textContent = total ? numero(total) : "";
    indicador.parentElement.setAttribute("aria-label", total ?
        "Mensajería, " + total + " mensajes sin leer" : "Mensajería");
}

function desplegable(detalle) {
    document.addEventListener("pointerdown", evento => {
        if (detalle.open && !detalle.contains(evento.target)) detalle.open = false;
    });
    detalle.addEventListener("keydown", evento => {
        if (evento.key === "Escape" && detalle.open) {
            detalle.open = false;
            detalle.querySelector("summary").focus();
        }
    });
}

if (campana) {
    desplegable(campana);
    if (raiz) {
        iniciarMensajeria(raiz);
    } else {
        const sincronizar = () => pedir("/sincronizacion?limite=1")
            .then(datos => mostrarContador(datos.no_leidos), () => mostrarContador(0));
        sincronizar();
        window.addEventListener("pageshow", evento => { if (evento.persisted) sincronizar(); });
        campana.addEventListener("toggle", () => { if (campana.open) sincronizar(); });
    }
}

function crear(etiqueta, clase, texto) {
    const elemento = document.createElement(etiqueta);
    if (clase) elemento.className = clase;
    if (texto !== undefined) elemento.textContent = texto;
    return elemento;
}

function boton(texto, clase) {
    const elemento = crear("button", clase, texto);
    elemento.type = "button";
    return elemento;
}

function iniciales(nombre) {
    const palabras = nombre.trim().split(/\s+/);
    return (palabras.length > 1 ? [palabras[0], palabras.at(-1)] : palabras)
        .map(palabra => Array.from(palabra)[0] || "").join("").toLocaleUpperCase("es");
}

const normalizar = texto => texto.normalize("NFD").replace(/\p{M}/gu, "").toLocaleLowerCase("es");
const perfil = persona => normalizar(persona.nombre + "|" + (persona.area || ""));
function contarPerfiles(personas) {
    const frecuencias = new Map();
    for (const persona of personas) {
        const clave = perfil(persona);
        frecuencias.set(clave, (frecuencias.get(clave) || 0) + 1);
    }
    return frecuencias;
}

function perfilSecundario(persona, frecuencias) {
    const codigo = frecuencias.get(perfil(persona)) > 1 ? persona.referencia.slice(-8) : "";
    return [persona.area, codigo].filter(Boolean).join(" · ");
}

const reloj = new Intl.DateTimeFormat("es-MX", { hour: "numeric", minute: "2-digit" });
const calendario = new Intl.DateTimeFormat("es-MX", { day: "numeric", month: "short" });
const fechaCompleta = new Intl.DateTimeFormat("es-MX", { dateStyle: "medium", timeStyle: "short" });
function hora(segundos, corta = false) {
    const fecha = new Date(segundos * 1000);
    const elemento = crear("time", corta ? "" : "mensajeria-hora",
        corta && fecha.toDateString() !== new Date().toDateString() ? calendario.format(fecha) : reloj.format(fecha));
    elemento.dateTime = fecha.toISOString();
    elemento.title = fechaCompleta.format(fecha);
    return elemento;
}

function tamano(bytes) {
    const unidad = bytes >= 1048576 ? [1048576, "MiB"] : bytes >= 1024 ? [1024, "KiB"] : [1, "B"];
    return new Intl.NumberFormat("es-MX", { maximumFractionDigits: 1 }).format(bytes / unidad[0]) + " " + unidad[1];
}

function icono(nombre) {
    const tipo = porId("mensajeria-formato-" + formato(nombre));
    return (tipo || porId("mensajeria-formato-archivo")).content.cloneNode(true);
}

function iniciarMensajeria(raiz) {
    const el = nombre => porId("mensajeria-" + nombre);
    const lista = el("conversaciones");
    const historial = el("historial");
    const shell = raiz.closest(".app-shell");
    const mensajes = el("mensajes");
    const dialogo = el("selector");
    const opciones = el("opciones");
    const texto = el("texto");
    const acciones = el("acciones");
    const movil = matchMedia("(max-width: 800px)");
    const chats = new Map();
    const filasChat = new Map();
    const visibles = new Map();
    let cursorChats, cursorMensajes, activo, cuota, adjunto, operacion;
    let peticionLista, peticionChat, peticionSelector, selector;
    let archivadas = false;
    let enviando = false;
    let marcando = false;
    let archivando = false;
    let falloSesion = false;
    let venceTarjeta;
    let ultimaActualizacion = 0;

    desplegable(acciones);

    function anunciar(mensaje, error = false) {
        const aviso = el("aviso");
        aviso.classList.toggle("error", error);
        aviso.classList.toggle("exito", !error);
        aviso.textContent = mensaje;
        aviso.hidden = !mensaje;
    }

    function guardarCuota(datos) {
        cuota = datos;
        el("cuota").textContent = cuota.restantes + " de " + cuota.limite + " envíos disponibles";
        controles();
    }

    function fallo(error) {
        if (error.estado === 401 || ["identidad_no_reconciliada", "generacion_cambio"].includes(error.message)) {
            falloSesion = true;
            chats.clear();
            filasChat.clear();
            lista.replaceChildren();
            mensajes.replaceChildren();
            visibles.clear();
            el("chat-titulo").textContent = "Mensajería no disponible";
            el("chat-avatar").textContent = "";
            el("chat-area").hidden = true;
            acciones.hidden = true;
            if (dialogo.open) {
                opciones.replaceChildren();
                el("mas-opciones").hidden = true;
            }
            mostrarContador(0);
            el("cuota").textContent = "";
            peticionChat?.abort();
            window.clearTimeout(venceTarjeta);
            controles();
        }
        return mensajeError(error);
    }

    function pintarBandeja() {
        const termino = normalizar(el("buscar").value.trim());
        const orden = [...chats.values()].sort((a, b) => (b.ultimo?.confirmado_utc || 0) - (a.ultimo?.confirmado_utc || 0));
        const frecuencias = contarPerfiles(orden.map(chat => chat.otro).filter(Boolean));
        let anterior = null;
        let cantidad = 0;
        for (const chat of orden) {
            let fila = filasChat.get(chat.id);
            if (!fila) {
                const entrada = boton("", "");
                const avatar = crear("span", "mensajeria-avatar");
                avatar.setAttribute("aria-hidden", "true");
                const identidad = crear("span", "mensajeria-fila-texto");
                const nombre = crear("strong");
                const resumen = crear("small");
                identidad.append(nombre, resumen);
                const datos = crear("span", "mensajeria-fila-datos");
                entrada.append(avatar, identidad, datos);
                const item = crear("li");
                item.append(entrada);
                entrada.addEventListener("click", () => abrirChat(chats.get(chat.id)));
                fila = { item, entrada, avatar, nombre, resumen, datos };
                filasChat.set(chat.id, fila);
            }
            const nombre = chat.otro?.nombre || "Usuario no disponible";
            const area = chat.otro ? perfilSecundario(chat.otro, frecuencias) : "";
            const coincide = normalizar([nombre, area, chat.ultimo?.texto || ""].join(" ")).includes(termino);
            fila.item.hidden = !coincide;
            if (coincide) cantidad++;
            fila.entrada.setAttribute("aria-current", String(activo?.id === chat.id));
            fila.avatar.textContent = iniciales(nombre);
            fila.nombre.textContent = nombre;
            fila.resumen.textContent = [area, chat.ultimo?.texto].filter(Boolean).join(" · ") || "Sin mensajes recientes";
            fila.entrada.setAttribute("aria-label", [nombre, area, chat.no_leidos ? chat.no_leidos + " sin leer" : ""]
                .filter(Boolean).join(", "));
            fila.datos.replaceChildren();
            if (chat.ultimo) fila.datos.append(hora(chat.ultimo.confirmado_utc, true));
            if (chat.no_leidos) fila.datos.append(crear("small", "mensajeria-contador", numero(chat.no_leidos)));
            const siguiente = anterior ? anterior.nextElementSibling : lista.firstElementChild;
            if (siguiente !== fila.item) lista.insertBefore(fila.item, siguiente);
            anterior = fila.item;
        }
        el("mas-chats").hidden = !cursorChats;
        el("estado-lista").textContent = cantidad ? "" : termino ?
            (cursorChats ? "Sin coincidencias en esta página. Puedes cargar más conversaciones." : "No hay coincidencias.") :
            archivadas ? "No tienes conversaciones archivadas." : "Aún no tienes conversaciones. Inicia una con el botón superior.";
    }

    function vaciarBandeja() {
        chats.clear();
        filasChat.clear();
        lista.replaceChildren();
        cursorChats = undefined;
    }

    async function cargarBandeja(mas = false, conservar = false) {
        peticionLista?.abort();
        const peticion = new AbortController();
        peticionLista = peticion;
        const filtro = new URLSearchParams({ archivadas });
        if (mas && cursorChats) filtro.set("despues", cursorChats);
        el("reintentar-lista").hidden = true;
        el("mas-chats").disabled = true;
        if (!chats.size) el("estado-lista").textContent = "Cargando conversaciones…";
        try {
            const datos = await pedir((mas ? "/conversaciones?" : "/sincronizacion?") + filtro, { signal: peticion.signal });
            if (peticion.signal.aborted) return;
            if (!mas) {
                falloSesion = false;
                mostrarContador(datos.no_leidos);
                guardarCuota(datos.cuota);
            }
            const pagina = mas ? datos : datos.conversaciones;
            if (!mas && !conservar) vaciarBandeja();
            pagina.elementos.forEach(chat => chats.set(chat.id, chat));
            if (!conservar || cursorChats === undefined) cursorChats = pagina.siguiente;
            pintarBandeja();
        } catch (error) {
            if (peticion.signal.aborted) return;
            el("estado-lista").textContent = fallo(error);
            el("reintentar-lista").hidden = false;
        } finally {
            if (peticionLista === peticion) el("mas-chats").disabled = false;
        }
    }

    function seleccionChat(chat) {
        return chat?.otro || { nombre: "Usuario no disponible", area: "" };
    }

    function abrirChat(chat, conservar = false) {
        if (!chat || enviando || (operacion?.incierta && !conservar)) return;
        if (activo?.id && activo.id === chat.id && !conservar) return;
        peticionChat?.abort();
        window.clearTimeout(venceTarjeta);
        acciones.open = false;
        if (!conservar) limpiarCompositor();
        activo = chat;
        cursorMensajes = null;
        visibles.clear();
        mensajes.replaceChildren();
        el("estado-historial").textContent = "";
        el("mas-mensajes").hidden = true;
        el("reintentar-historial").hidden = true;
        const persona = seleccionChat(chat);
        el("chat-titulo").textContent = persona.nombre;
        el("chat-avatar").textContent = iniciales(persona.nombre);
        el("chat-area").textContent = persona.area || "";
        el("chat-area").hidden = !persona.area;
        el("archivar").textContent = chat.archivada ? "Mover a activas" : "Archivar conversación";
        acciones.hidden = !chat.id;
        raiz.dataset.abierta = "";
        raiz.querySelector(".mensajeria-bienvenida").hidden = true;
        raiz.querySelector(".mensajeria-chat").hidden = false;
        pintarBandeja();
        controles();
        el("chat-titulo").focus({ preventScroll: true });
        if (chat.id) cargarHistorial();
        else el("estado-historial").textContent = "Escribe y adjunta un archivo para iniciar la conversación.";
    }

    function volver(foco = true) {
        if (enviando || operacion?.incierta) return;
        const seleccionado = activo;
        activo = null;
        peticionChat?.abort();
        window.clearTimeout(venceTarjeta);
        visibles.clear();
        mensajes.replaceChildren();
        limpiarCompositor();
        delete raiz.dataset.abierta;
        raiz.querySelector(".mensajeria-bienvenida").hidden = false;
        raiz.querySelector(".mensajeria-chat").hidden = true;
        pintarBandeja();
        if (foco) (filasChat.get(seleccionado?.id)?.entrada || el("bandeja-titulo")).focus();
    }

    function burbuja(mensaje) {
        const saliente = mensaje.enviado;
        const item = crear("li", "mensajeria-mensaje" + (saliente ? " enviado" : ""));
        const cuerpo = crear("div", "mensajeria-burbuja");
        cuerpo.append(crear("span", "sr-only", saliente ? "Enviado" : "Recibido"));
        cuerpo.append(crear("p", "mensajeria-texto", mensaje.texto));
        const tarjeta = crear("div", "mensajeria-tarjeta", "Comprobando adjunto…");
        cuerpo.append(tarjeta, hora(mensaje.confirmado_utc));
        item.append(cuerpo);
        const datos = { mensaje, item, tarjeta, vence: null };
        visibles.set(mensaje.id, datos);
        return datos;
    }

    function tarjetaNoDisponible(fila) {
        fila.vence = null;
        fila.tarjeta.textContent = "Documento no disponible";
    }

    function tarjetaPorComprobar(fila, chat) {
        fila.vence = null;
        const comprobar = boton("Comprobar adjunto", "mensajeria-secundario");
        comprobar.addEventListener("click", () => {
            comprobar.disabled = true;
            comprobarTarjetas([fila], chat, peticionChat.signal);
        });
        fila.tarjeta.replaceChildren(comprobar);
    }

    function pintarTarjeta(fila, datos, chat) {
        if (datos.estado !== "disponible" || datos.vence_utc * 1000 <= Date.now()) {
            tarjetaNoDisponible(fila);
            return;
        }
        fila.vence = datos.vence_utc * 1000;
        const nombre = datos.nombre_original;
        const detalle = crear("span", "mensajeria-archivo-datos");
        const origen = datos.origen === "biblioteca" ? "Biblioteca" : "Archivo externo";
        const vence = "Disponible hasta " + fechaCompleta.format(new Date(fila.vence));
        detalle.append(crear("strong", "", nombre), crear("small", "",
            [origen, datos.tamano_bytes ? tamano(datos.tamano_bytes) : "", vence].filter(Boolean).join(" · ")));
        fila.tarjeta.replaceChildren(icono(nombre), detalle);
        if (datos.acciones.includes("descargar")) {
            const enlace = crear("a", "", "Descargar");
            enlace.href = API + "/conversaciones/" + chat + "/mensajes/" + fila.mensaje.id + "/adjunto/descarga";
            enlace.download = "";
            enlace.setAttribute("aria-label", "Descargar " + nombre);
            fila.tarjeta.append(enlace);
        }
        if (datos.visualizacion_pendiente) detalle.append(crear("small", "", "Vista previa segura pendiente."));
    }

    function programarVencimientos() {
        window.clearTimeout(venceTarjeta);
        const ahora = Date.now();
        let proximo = Infinity;
        for (const [id, fila] of visibles) {
            const venceMensaje = fila.mensaje.historial_vence_utc * 1000;
            if (venceMensaje <= ahora) {
                fila.item.remove();
                visibles.delete(id);
                continue;
            }
            proximo = Math.min(proximo, venceMensaje);
            if (!fila.vence) continue;
            if (fila.vence <= ahora) tarjetaNoDisponible(fila);
            else proximo = Math.min(proximo, fila.vence);
        }
        if (!visibles.size && activo?.id && !falloSesion) {
            el("estado-historial").textContent = "No hay mensajes en el historial de los últimos 15 días.";
        }
        controles();
        if (Number.isFinite(proximo)) venceTarjeta = window.setTimeout(programarVencimientos, Math.max(1, proximo - Date.now()));
    }

    async function comprobarTarjetas(filas, chat, signal) {
        const cola = filas.values();
        async function comprobar() {
            for (const fila of cola) {
                if (signal.aborted) break;
                try {
                    const datos = await pedir("/conversaciones/" + chat + "/mensajes/" + fila.mensaje.id + "/adjunto", { signal });
                    if (!signal.aborted) pintarTarjeta(fila, datos, chat);
                } catch (error) {
                    if (signal.aborted) break;
                    tarjetaNoDisponible(fila);
                    if (error.estado === 401 || error.message === "identidad_no_reconciliada") {
                        el("estado-historial").textContent = fallo(error);
                        break;
                    }
                }
            }
        }
        await Promise.all(Array.from({ length: Math.min(filas.length, 4) }, comprobar));
        if (!signal.aborted) programarVencimientos();
    }

    async function cargarHistorial(mas = false, actualizar = false) {
        const chat = activo?.id;
        if (!referencia(chat)) return;
        peticionChat?.abort();
        const peticion = new AbortController();
        peticionChat = peticion;
        const filtro = new URLSearchParams({ limite: 20 });
        if (mas && cursorMensajes) filtro.set("antes", cursorMensajes);
        el("reintentar-historial").hidden = true;
        el("mas-mensajes").disabled = true;
        if (!visibles.size) el("estado-historial").textContent = "Cargando historial…";
        try {
            const pagina = await pedir("/conversaciones/" + chat + "/mensajes?" + filtro, { signal: peticion.signal });
            if (peticion.signal.aborted) return;
            const previamente = historial.scrollHeight;
            const abajo = historial.scrollHeight - historial.scrollTop - historial.clientHeight < 60;
            if (!actualizar || !visibles.size) cursorMensajes = pagina.siguiente;
            const primeras = [...pagina.elementos].reverse();
            const filas = [];
            for (const mensaje of primeras) {
                if (!referencia(mensaje.id)) continue;
                const previa = visibles.get(mensaje.id);
                if (previa) {
                    previa.mensaje = mensaje;
                    if (!previa.vence) filas.push(previa);
                    continue;
                }
                filas.push(burbuja(mensaje));
            }
            const nuevas = document.createDocumentFragment();
            for (const fila of filas) if (!fila.item.isConnected) nuevas.append(fila.item);
            if (mas) mensajes.prepend(nuevas);
            else mensajes.append(nuevas);
            el("estado-historial").textContent = visibles.size ? "" : "No hay mensajes en el historial de los últimos 15 días.";
            el("mas-mensajes").hidden = !cursorMensajes;
            controles();
            if (mas) historial.scrollTop += historial.scrollHeight - previamente;
            else if (!actualizar || abajo) historial.scrollTop = historial.scrollHeight;
            await comprobarTarjetas(filas, chat, peticion.signal);
            if (!peticion.signal.aborted && !mas && (!actualizar || abajo)) historial.scrollTop = historial.scrollHeight;
        } catch (error) {
            if (peticion.signal.aborted) return;
            el("estado-historial").textContent = fallo(error);
            el("reintentar-historial").hidden = false;
        } finally {
            if (peticionChat === peticion) el("mas-mensajes").disabled = false;
        }
    }

    function controles() {
        const bloqueado = enviando || operacion?.incierta;
        const longitud = caracteres(texto.value);
        const destinatario = activo?.otro?.referencia;
        el("caracteres").textContent = longitud + " / 300";
        texto.setAttribute("aria-invalid", String(longitud > 300));
        texto.disabled = Boolean(bloqueado || falloSesion || !destinatario);
        for (const nombre of ["adjuntar", "biblioteca"]) el(nombre).disabled = texto.disabled;
        const quitar = el("adjunto-elegido").querySelector("button");
        if (quitar) quitar.disabled = texto.disabled;
        el("nuevo").disabled = Boolean(bloqueado || falloSesion);
        el("volver").disabled = Boolean(bloqueado);
        el("archivar").disabled = Boolean(bloqueado || archivando || falloSesion);
        el("leer").hidden = ![...visibles.values()].some(({ mensaje }) =>
            !mensaje.leido_utc && !mensaje.enviado);
        el("leer").disabled = Boolean(bloqueado || marcando || falloSesion);
        el("descartar").hidden = !operacion?.incierta || enviando;
        el("enviar").textContent = operacion ? "Reintentar" : "Enviar";
        el("enviar").disabled = Boolean(enviando || archivando || falloSesion || !destinatario || !adjunto || !textoValido(texto.value) ||
            (cuota?.restantes === 0 && !operacion?.incierta));
    }

    function elegirAdjunto(elegido) {
        adjunto = elegido;
        operacion = null;
        const contenedor = el("adjunto-elegido");
        contenedor.replaceChildren();
        contenedor.hidden = !elegido;
        if (elegido) {
            const tarjeta = crear("div", "mensajeria-tarjeta");
            const archivo = elegido.archivo;
            const nombre = archivo ? archivo.name : elegido.nombre;
            const datos = crear("span", "mensajeria-archivo-datos");
            datos.append(crear("strong", "", nombre), crear("small", "", archivo ?
                formato(nombre).toUpperCase() + " · " + tamano(archivo.size) : "Biblioteca · Visualizar y descargar"));
            const quitar = boton("Quitar", "mensajeria-secundario");
            quitar.setAttribute("aria-label", "Quitar adjunto");
            quitar.addEventListener("click", () => { elegirAdjunto(null); el("adjuntar").focus(); });
            tarjeta.append(icono(nombre), datos, quitar);
            contenedor.append(tarjeta);
        }
        controles();
    }

    function limpiarCompositor() {
        texto.value = "";
        elegirAdjunto(null);
        anunciar("");
        el("transferencia").hidden = true;
    }

    function estadoEnvio(etapa, avance) {
        el("transferencia").hidden = !etapa;
        el("fase-envio").textContent = etapa || "";
        el("progreso").hidden = avance === null;
        if (avance !== null) el("progreso").value = avance;
    }

    async function buscarConversacion(destinatario) {
        for (const bandeja of [archivadas, !archivadas]) {
            let despues = null;
            do {
                const filtro = new URLSearchParams({ archivadas: bandeja, limite: 50 });
                if (despues) filtro.set("despues", despues);
                const pagina = await pedir("/conversaciones?" + filtro);
                const encontrada = pagina.elementos.find(chat => chat.otro?.referencia === destinatario);
                if (encontrada) return encontrada;
                despues = pagina.siguiente;
            } while (despues);
        }
        return null;
    }

    async function enviarMensaje(evento) {
        evento.preventDefault();
        if (el("enviar").disabled) return;
        const destinatario = activo.otro.referencia;
        operacion ||= { destinatario, texto: texto.value, adjunto, clave: crypto.randomUUID().replaceAll("-", "") };
        enviando = true;
        anunciar("");
        controles();
        try {
            await enviar(operacion, estadoEnvio);
        } catch (error) {
            operacion.incierta ||= error.resultadoIncierto === true;
            if (!operacion.incierta && error.estado === 410) operacion = null;
            const aviso = fallo(error);
            anunciar(operacion?.incierta ? aviso + " El resultado del envío es incierto. Reintenta la misma operación." : aviso, true);
            if (error.message === "cuota_agotada") guardarCuota(await pedir("/cuota").catch(() => ({ restantes: 0, limite: 50 })));
            return;
        } finally {
            estadoEnvio(null, null);
            enviando = false;
            controles();
        }
        limpiarCompositor();
        anunciar("Mensaje enviado.");
        if (!activo.id) {
            const pendiente = activo;
            const chat = await buscarConversacion(destinatario).catch(() => null);
            if (activo === pendiente && chat) {
                if (chat.archivada !== archivadas) {
                    archivadas = chat.archivada;
                    actualizarPestanas();
                    vaciarBandeja();
                }
                chats.set(chat.id, chat);
                abrirChat(chat, true);
            }
        } else {
            cargarHistorial(false, true);
        }
        cargarBandeja(false, true);
    }

    function actualizarPestanas() {
        for (const pestaña of raiz.querySelectorAll("[data-bandeja]")) {
            pestaña.setAttribute("aria-pressed", String((pestaña.dataset.bandeja === "archivadas") === archivadas));
        }
    }

    async function cambiarArchivo() {
        if (!activo?.id || el("archivar").disabled) return;
        const chat = activo;
        archivando = true;
        controles();
        try {
            await pedir("/conversaciones/" + chat.id + "/archivo", { post: true, datos: { archivada: !chat.archivada } });
            if (activo === chat) volver();
            vaciarBandeja();
            cargarBandeja();
        } catch (error) {
            if (activo === chat) anunciar(fallo(error), true);
        } finally {
            archivando = false;
            controles();
        }
    }

    async function marcarLectura() {
        if (!activo?.id || el("leer").disabled) return;
        const chat = activo;
        marcando = true;
        controles();
        try {
            for (const fila of visibles.values()) {
                const mensaje = fila.mensaje;
                if (activo !== chat) break;
                if (!mensaje.enviado && !mensaje.leido_utc) {
                    const datos = await pedir("/conversaciones/" + chat.id + "/mensajes/" + mensaje.id + "/lectura", { post: true });
                    if (datos) mensaje.leido_utc = true;
                }
            }
        } catch (error) {
            if (activo === chat) anunciar(fallo(error), true);
        } finally {
            marcando = false;
            if (activo === chat) {
                acciones.open = false;
                acciones.querySelector("summary").focus();
            }
            controles();
            cargarBandeja(false, true);
        }
    }

    function abrirSelector(tipo) {
        selector = { tipo, cursor: null, elementos: new Map(), filtro: "" };
        el("selector-titulo").textContent = tipo === "personas" ? "Nueva conversación" : "Seleccionar de Biblioteca";
        el("filtro-selector").placeholder = tipo === "personas" ? "Nombre o área" : "Título o nombre de archivo";
        el("filtro-selector").value = "";
        el("nota-selector").hidden = tipo !== "documentos";
        opciones.replaceChildren();
        dialogo.showModal();
        cargarOpciones();
    }

    async function cargarOpciones(mas = false) {
        const estado = selector;
        peticionSelector?.abort();
        const peticion = new AbortController();
        peticionSelector = peticion;
        const personas = estado.tipo === "personas";
        const filtro = new URLSearchParams();
        if (!personas) {
            filtro.set("destinatario", activo.otro.referencia);
            filtro.set("buscar", estado.filtro);
        }
        if (mas && estado.cursor) filtro.set("despues", estado.cursor);
        el("estado-selector").textContent = "Cargando…";
        el("mas-opciones").disabled = true;
        try {
            const datos = personas ? await pedir("/destinatarios?" + filtro, { signal: peticion.signal }) :
                await buscarDocumentos(filtro, peticion.signal);
            if (peticion.signal.aborted) return;
            if (!mas) estado.elementos.clear();
            datos.elementos.forEach(item => estado.elementos.set(item.referencia, item));
            estado.cursor = datos.siguiente;
            pintarOpciones();
            if (!personas && !datos.descarga) el("estado-selector").textContent =
                "La modalidad de descarga no está disponible para ambos participantes.";
        } catch (error) {
            if (!peticion.signal.aborted) el("estado-selector").textContent = fallo(error);
        } finally {
            if (peticionSelector === peticion) el("mas-opciones").disabled = false;
        }
    }

    function pintarOpciones() {
        const personas = selector.tipo === "personas";
        const termino = normalizar(selector.filtro);
        const frecuencias = personas ? contarPerfiles(selector.elementos.values()) : null;
        opciones.replaceChildren();
        for (const opcion of selector.elementos.values()) {
            if (!referencia(opcion.referencia) || (personas && !normalizar([opcion.nombre, opcion.area || ""].join(" ")).includes(termino))) continue;
            const item = crear("li");
            const elegir = boton("", "");
            const identidad = crear("span", "mensajeria-fila-texto");
            identidad.append(crear("strong", "", opcion.nombre), crear("small", "",
                personas ? perfilSecundario(opcion, frecuencias) : opcion.nombreArchivo));
            const avatar = personas ? crear("span", "mensajeria-avatar", iniciales(opcion.nombre)) : icono(opcion.nombreArchivo);
            if (personas) avatar.setAttribute("aria-hidden", "true");
            elegir.append(avatar, identidad);
            elegir.addEventListener("click", () => {
                dialogo.close();
                if (!personas) {
                    elegirAdjunto({ referencia: opcion.referencia, nombre: opcion.nombreArchivo });
                    texto.focus();
                    return;
                }
                const existente = [...chats.values()].find(chat => chat.otro?.referencia === opcion.referencia);
                abrirChat(existente || { id: null, otro: opcion, archivada: false });
            });
            item.append(elegir);
            opciones.append(item);
        }
        el("estado-selector").textContent = opciones.children.length ? "" :
            selector.cursor ? "Sin coincidencias en esta página. Puedes cargar más." : "No se encontraron opciones disponibles.";
        el("mas-opciones").hidden = !selector.cursor;
    }

    el("nuevo").addEventListener("click", () => abrirSelector("personas"));
    el("biblioteca").addEventListener("click", () => abrirSelector("documentos"));
    el("buscar-selector").addEventListener("submit", evento => {
        evento.preventDefault();
        selector.filtro = el("filtro-selector").value.trim();
        if (selector.tipo === "personas") pintarOpciones();
        else {
            selector.cursor = null;
            selector.elementos.clear();
            opciones.replaceChildren();
            el("mas-opciones").hidden = true;
            cargarOpciones();
        }
    });
    el("mas-opciones").addEventListener("click", () => cargarOpciones(true));
    dialogo.addEventListener("close", () => peticionSelector?.abort());
    el("buscar").addEventListener("input", pintarBandeja);
    for (const pestaña of raiz.querySelectorAll("[data-bandeja]")) {
        pestaña.addEventListener("click", () => {
            const destino = pestaña.dataset.bandeja === "archivadas";
            if (archivadas === destino) return;
            archivadas = destino;
            actualizarPestanas();
            vaciarBandeja();
            cargarBandeja();
        });
    }
    el("volver").addEventListener("click", () => volver());
    el("mas-chats").addEventListener("click", () => cargarBandeja(true));
    el("reintentar-lista").addEventListener("click", () => cargarBandeja());
    el("mas-mensajes").addEventListener("click", () => cargarHistorial(true));
    el("reintentar-historial").addEventListener("click", () => cargarHistorial(false, true));
    el("archivar").addEventListener("click", cambiarArchivo);
    el("leer").addEventListener("click", marcarLectura);
    texto.addEventListener("input", () => { operacion = null; controles(); });
    el("adjuntar").addEventListener("click", () => el("archivo").click());
    el("archivo").addEventListener("change", () => {
        const archivo = el("archivo").files[0];
        el("archivo").value = "";
        if (!archivo) return;
        if (!archivo.size || archivo.size > LIMITE || !["pdf", "docx", "xlsx", "pptx", "txt", "png", "jpg", "jpeg"].includes(formato(archivo.name))) {
            anunciar("Elige un archivo de formato permitido, con contenido y de hasta 20 MiB.", true);
            return;
        }
        anunciar("");
        elegirAdjunto({ archivo });
    });
    el("compositor").addEventListener("submit", enviarMensaje);
    el("descartar").addEventListener("click", () => {
        operacion = null;
        anunciar("Reintento descartado. Consulta el historial antes de iniciar otro envío.", true);
        controles();
        if (activo?.id) cargarHistorial(false, true);
        cargarBandeja(false, true);
    });

    function actualizarDesdeServidor() {
        if (document.hidden || enviando || Date.now() - ultimaActualizacion < 5000) return;
        ultimaActualizacion = Date.now();
        cargarBandeja(false, true);
        if (activo?.id) {
            for (const fila of visibles.values()) tarjetaPorComprobar(fila, activo.id);
            cargarHistorial(false, true);
        }
    }

    // Los eventos mínimos de una futura conexión pueden solicitar esta misma actualización HTTP.
    document.addEventListener("siged:mensajeria-actualizar", actualizarDesdeServidor);
    document.addEventListener("visibilitychange", actualizarDesdeServidor);
    window.addEventListener("pageshow", evento => { if (evento.persisted) actualizarDesdeServidor(); });
    campana.addEventListener("toggle", () => { if (campana.open) actualizarDesdeServidor(); });
    function ajustarVista() {
        const menu = document.querySelector(".sidebar-menu");
        menu.open = !movil.matches;
        if (movil.matches && activo && document.activeElement?.closest(".mensajeria-bandeja")) el("chat-titulo").focus();
    }
    function ajustarTeclado() {
        const viewport = window.visualViewport;
        const altura = viewport?.scale === 1 && movil.matches ? Math.floor(viewport.height) : 0;
        if (altura) shell.style.setProperty("--mensajeria-viewport", altura + "px");
        else shell.style.removeProperty("--mensajeria-viewport");
        shell.toggleAttribute("data-mensajeria-compacta", altura > 0 && altura < 500);
    }
    movil.addEventListener("change", ajustarVista);
    window.visualViewport?.addEventListener("resize", ajustarTeclado);
    ajustarVista();
    ajustarTeclado();
    cargarBandeja();
}
