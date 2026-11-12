(() => {
    if (!window.clippy) return;
    const config = window.sigedClippyConfig;
    if (!config) return;
    clippy.BASE_PATH = config.basePath;

    function cargarAsistente() {
        clippy.load("Clippy", (agente) => {
            window.sigedClippy = agente;
            const mensajeria = document.getElementById("mensajeria");
            const compositor = mensajeria && document.getElementById("mensajeria-compositor");
            const textoMensaje = mensajeria && document.getElementById("mensajeria-texto");
            const enviarMensaje = mensajeria && document.getElementById("mensajeria-enviar");
            const limiteBocadillo = mensajeria ? 120 : 240;
            const elegirAnimacionInactiva = agente._getIdleAnimation.bind(agente);
            agente._getIdleAnimation = () => agente.hasAnimation("Idle1_1")
                ? "Idle1_1" : elegirAnimacionInactiva();
            const movimientoReducido = window.matchMedia("(prefers-reduced-motion: reduce)");
            const iniciarAnimacionReposo = agente._onQueueEmpty.bind(agente);
            agente._onQueueEmpty = () => {
                if (!movimientoReducido.matches) iniciarAnimacionReposo();
            };
            agente._queue._onEmptyCallback = () => agente._onQueueEmpty();
            let temporizadorInactivo;
            let temporizadorSaludo;
            let accionSaludo;
            const globo = agente._balloon;
            const programarReposo = (espera = 1200) => {
                window.clearTimeout(temporizadorInactivo);
                temporizadorInactivo = window.setTimeout(() => {
                    const figura = document.querySelector(".clippy");
                    const bocadillo = document.querySelector(".clippy-balloon");
                    const mensajeVisible = bocadillo && getComputedStyle(bocadillo).display !== "none";
                    if (mensajeVisible || figura?.matches(":hover, :focus-visible")) {
                        programarReposo(1000);
                        return;
                    }
                    figura?.classList.add("clippy-inactivo");
                }, espera);
            };
            const ocultarOriginal = globo.hide.bind(globo);
            globo.hide = (inmediato) => {
                // Un mensaje anterior puede terminar justo después de empezar
                // el siguiente. No debe programar su cierre mientras habla.
                if (!inmediato && globo._active) return;
                if (!inmediato && accionSaludo && !accionSaludo.hidden &&
                    document.querySelector(".clippy-balloon")?.matches(":hover")) return;
                ocultarOriginal(inmediato);
            };
            const cerrarSaludo = () => {
                window.clearTimeout(globo._hiding);
                globo._hiding = null;
                globo._hidden = true;
                globo._balloon.hide();
                if (accionSaludo) accionSaludo.hidden = true;
                programarReposo();
            };
            const programarCierreSaludo = (espera) => {
                window.clearTimeout(temporizadorSaludo);
                temporizadorSaludo = window.setTimeout(cerrarSaludo, espera);
            };
            const hablarOriginal = agente.speak.bind(agente);
            agente.speak = (mensaje, mantener) => {
                window.clearTimeout(temporizadorSaludo);
                if (accionSaludo) accionSaludo.hidden = true;
                const figura = document.querySelector(".clippy");
                figura?.classList.remove("clippy-inactivo");
                window.clearTimeout(temporizadorInactivo);
                ajustarBocadillo();
                // Cancelar solo el cierre anterior: pausar el globo detendría
                // la escritura y dejaría bloqueada la cola de mensajes.
                window.clearTimeout(globo._hiding);
                globo._hiding = null;
                globo.CLOSE_BALLOON_DELAY = mantener ? 35000 : 2000;
                hablarOriginal(mensaje, false);
                programarReposo(Math.max(6000, String(mensaje).split(/\s+/).length * 220 + 3000));
            };
            const ajustarBocadillo = () => {
                const figura = document.querySelector(".clippy");
                const bocadillo = document.querySelector(".clippy-balloon");
                if (!figura || !bocadillo) return;
                const arriba = parseFloat(figura.style.top) || 0;
                const espacioMinimo = Math.min(160, Math.max(80, window.innerHeight - 32));
                const abajo = Math.min(Math.max(16, window.innerHeight - arriba + 16), window.innerHeight - espacioMinimo);
                bocadillo.style.setProperty("--clippy-bocadillo-abajo", `${abajo}px`);
            };
            const ubicar = () => {
                const alto = window.innerHeight;
                const figuraActual = document.querySelector(".clippy");
                const bocadilloActual = document.querySelector(".clippy-balloon");
                if (!mensajeria && (figuraActual?.matches(":hover, :focus-visible") ||
                    (bocadilloActual && getComputedStyle(bocadilloActual).display !== "none"))) return;
                const inactivo = figuraActual?.classList.contains("clippy-inactivo");
                const escala = inactivo ? (window.innerWidth <= 700 ? 0.40 : 0.50) : 1;
                const anchoFigura = 124 * escala;
                const altoFigura = 93 * escala;
                // Reservar también el espacio que ocupará al volver a tamaño completo.
                const minimoX = 8 + (124 - anchoFigura);
                const minimoY = Math.min(170, Math.max(8, alto - 109)) + (93 - altoFigura);
                // El bocadillo está anclado al borde derecho: mantener también
                // allí al personaje evita separarlos y cubrir el centro de la página.
                const xs = [minimoX + Math.max(0, window.innerWidth - anchoFigura - 8 - minimoX)];
                const ys = [0.5, 0.35, 0.65, 0.2, 0.8, 0.05, 0.95].map(fraccion =>
                    minimoY + Math.max(0, alto - altoFigura - 8 - minimoY) * fraccion);
                const controles = Array.from(document.querySelectorAll(
                    ".app-content button, .app-content a, .app-content input, .kpi-card, .almacenamiento-panel, .archivo-fila, .barra-seleccion, .sidebar a, .sidebar button"
                )).filter(elemento => elemento.getClientRects().length).map(elemento => elemento.getBoundingClientRect());
                const protegidos = mensajeria ? Array.from(document.querySelectorAll(
                    ".app-topbar, .mensajeria-bandeja-cabecera, .mensajeria-chat-cabecera, #mensajeria-compositor, " +
                    ".mensajeria-campana[open] .mensajeria-notificaciones, .mensajeria-chat-acciones[open] > div"
                )).filter(elemento => elemento.getClientRects().length).map(elemento => elemento.getBoundingClientRect()) : [];
                for (const rect of protegidos) {
                    const antes = rect.top - altoFigura - 4;
                    if (antes >= minimoY && antes + altoFigura <= alto - 8) ys.push(antes);
                }
                const area = (a, b) => Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) *
                    Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
                let mejor = { puntaje: Infinity, izquierda: xs[0], arriba: ys[0] };
                let mejorLibre;
                for (const izquierda of xs) for (const arriba of ys) {
                    const figura = { left: izquierda - 4, right: izquierda + anchoFigura + 4,
                        top: arriba - 4, bottom: arriba + altoFigura + 4 };
                    const arribaExpandido = arriba - (93 - altoFigura);
                    const figuraExpandida = {left: izquierda - (124 - anchoFigura) - 4, right: izquierda + anchoFigura + 4,
                        top: arribaExpandido - 4, bottom: arriba + altoFigura + 4};
                    const espacioMinimo = Math.min(160, Math.max(80, alto - 32));
                    const abajo = Math.min(Math.max(16, alto - arribaExpandido + 16), alto - espacioMinimo);
                    const alturaConsejo = Math.max(0, Math.min(limiteBocadillo, alto - abajo - 12));
                    const consejo = {left: Math.max(12, window.innerWidth - 272), right: window.innerWidth - 12,
                        top: alto - abajo - alturaConsejo, bottom: alto - abajo};
                    const puntaje = controles.reduce((total, rectangulo) => total + area(figura, rectangulo) +
                        area(figuraExpandida, rectangulo) + area(consejo, rectangulo) * 0.4, 0) +
                        protegidos.reduce((total, rect) => total + 4 * area(figuraExpandida, rect), 0);
                    if (puntaje < mejor.puntaje) mejor = { puntaje, izquierda, arriba };
                    if (mensajeria && alturaConsejo >= 100 && (!mejorLibre || puntaje < mejorLibre.puntaje) &&
                        protegidos.every(rect => !area(figuraExpandida, rect) && !area(consejo, rect))) {
                        mejorLibre = { puntaje, izquierda, arriba };
                    }
                }
                if (mejorLibre) mejor = mejorLibre;
                else if (mensajeria && bocadilloActual && getComputedStyle(bocadilloActual).display !== "none") {
                    agente.stop();
                    globo.hide(true);
                }
                const x = mejor.izquierda - (124 - anchoFigura);
                const y = mejor.arriba - (93 - altoFigura);
                if (mensajeria && figuraActual) {
                    // moveTo encola el movimiento detrás del consejo que se está mostrando.
                    figuraActual.style.left = `${x}px`;
                    figuraActual.style.top = `${y}px`;
                    ajustarBocadillo();
                } else {
                    agente.moveTo(x, y, 0);
                    window.requestAnimationFrame(ajustarBocadillo);
                }
                return !mensajeria || Boolean(mejorLibre);
            };
            ubicar();
            agente.show(true);
            document.querySelector(".clippy")?.classList.add("clippy-inactivo");
            ubicar();
            const bocadillo = document.querySelector(".clippy-balloon");
            if (bocadillo) {
                if (mensajeria) bocadillo.style.setProperty("--clippy-bocadillo-alto", `${limiteBocadillo}px`);
                const cerrarConsejo = document.createElement("button");
                cerrarConsejo.type = "button";
                cerrarConsejo.className = "clippy-cerrar";
                cerrarConsejo.setAttribute("aria-label", "Cerrar consejo de Clippy");
                cerrarConsejo.title = "Cerrar consejo";
                cerrarConsejo.textContent = "×";
                cerrarConsejo.addEventListener("click", (evento) => {
                    evento.stopPropagation();
                    window.clearTimeout(temporizadorSaludo);
                    agente.stop();
                    bocadillo.style.display = "none";
                    programarReposo();
                });
                bocadillo.append(cerrarConsejo);
                accionSaludo = document.createElement("a");
                accionSaludo.className = "clippy-accion";
                accionSaludo.hidden = true;
                bocadillo.append(accionSaludo);
                bocadillo.addEventListener("mouseenter", () => {
                    window.clearTimeout(temporizadorSaludo);
                    if (!accionSaludo.hidden) {
                        window.clearTimeout(globo._hiding);
                        globo._hiding = null;
                    }
                });
                bocadillo.addEventListener("mouseleave", () => {
                    if (!accionSaludo.hidden) programarCierreSaludo(15000);
                });
            }
            window.addEventListener("resize", ubicar);
            window.addEventListener("scroll", () => ubicar(), { passive: true });
            if (compositor) {
                const retirarConsejo = () => {
                    if (bocadillo && getComputedStyle(bocadillo).display !== "none") {
                        agente.stop();
                        globo.hide(true);
                        programarReposo();
                    }
                };
                textoMensaje.addEventListener("focus", retirarConsejo);
                document.addEventListener("input", retirarConsejo);
                compositor.addEventListener("submit", retirarConsejo);
                new ResizeObserver(ubicar).observe(compositor);
                document.getElementById("mensajeria-campana")?.addEventListener("toggle", ubicar);
                document.getElementById("mensajeria-acciones")?.addEventListener("toggle", ubicar);
            }

            let sonidosDesbloqueados = false;
            const habilitarEfectos = () => {
                if (sonidosDesbloqueados) return;
                sonidosDesbloqueados = true;
                const sonidos = Object.values(agente._animator?._sounds || {});
                sonidos.forEach((sonido) => {
                    const estabaSilenciado = sonido.muted;
                    sonido.muted = true;
                    const intento = sonido.play();
                    if (intento && typeof intento.then === "function") {
                        intento.then(() => {
                            sonido.pause();
                            try { sonido.currentTime = 0; } catch (_) { /* Audio todavía no listo. */ }
                            sonido.muted = estabaSilenciado;
                        }).catch(() => {
                            sonido.muted = estabaSilenciado;
                        });
                    } else {
                        sonido.pause();
                        try { sonido.currentTime = 0; } catch (_) { /* Audio todavía no listo. */ }
                        sonido.muted = estabaSilenciado;
                    }
                });
                window.removeEventListener("pointerdown", habilitarEfectos, true);
                window.removeEventListener("keydown", habilitarEfectos, true);
            };
            window.addEventListener("pointerdown", habilitarEfectos, { capture: true, once: true });
            window.addEventListener("keydown", habilitarEfectos, { capture: true, once: true });

            const ruta = window.location.pathname;
            // Consejos breves del personaje: pueden incluir el estado de la página.
            // Las preguntas explícitas se responden por separado con el catálogo.
            let ayudaDeEstaSeccion = "Puedo orientarte sobre esta sección. Haz clic en mí cuando quieras otro consejo.";
            if (ruta === "/inicio") {
                ayudaDeEstaSeccion = "En Inicio puedes consultar indicadores, avisos y los documentos recientes.";
            } else if (ruta === "/") {
                ayudaDeEstaSeccion = "En Biblioteca usa Buscar y filtrar para precisar documentos." +
                    (config.puedeVerExpedientes ? " Expedientes tiene su propio acceso en el menú lateral." : "");
            } else if (ruta === "/subir") {
                ayudaDeEstaSeccion = "En Subir documento, completa título y categoría, y selecciona un archivo permitido de hasta 20 MB.";
            } else if (ruta === "/expedientes") {
                ayudaDeEstaSeccion = "Abre una carpeta para consultar el expediente y sus documentos visibles." +
                    (config.puedeGestionarExpedientes ? " Usa Nuevo expediente para crear uno." : "");
            } else if (ruta === "/expedientes/nuevo") {
                ayudaDeEstaSeccion = config.puedeGestionarExpedientes ? "Escribe el nombre o asunto y, si deseas, una descripción. Al crear el expediente, NexusGrid asigna el folio." : "Consulta el explorador de expedientes para abrir los asuntos disponibles.";
            } else if (ruta.startsWith("/expedientes/") && ruta.endsWith("/eliminar")) {
                ayudaDeEstaSeccion = "Revisa el folio antes de confirmar: solo se elimina la ficha y sus vínculos; los originales permanecen en Biblioteca.";
            } else if (ruta.startsWith("/expedientes/")) {
                ayudaDeEstaSeccion = config.puedeGestionarExpedientes ? "En la ficha puedes buscar documentos y vincular uno o varios al expediente." : "En la ficha puedes consultar el expediente.";
                if (typeof config.cantidadExpediente === "number") {
                    const cantidad = config.cantidadExpediente;
                    const plural = cantidad === 1 ? "" : "s";
                    ayudaDeEstaSeccion = `Este expediente tiene ${cantidad} documento${plural} vinculado${plural}.` +
                        (config.puedeGestionarExpedientes ? " Busca por oficio, registro o parte del título para localizar otros documentos del mismo asunto." : "");
                }
            } else if (ruta === "/papelera") {
                ayudaDeEstaSeccion = "En Papelera puedes seleccionar varios documentos y restaurarlos; la eliminación definitiva no se puede deshacer.";
            } else if (ruta.startsWith("/usuarios/")) {
                ayudaDeEstaSeccion = "Desde la ficha de usuario puedes actualizar sus datos y administrar el acceso según su rol.";
            } else if (ruta === "/usuarios") {
                ayudaDeEstaSeccion = "Al crear una cuenta, asigna el área correcta. Lector consulta documentos, Editor también registra y restaura, y Administrador gestiona usuarios y eliminaciones definitivas.";
            } else if (ruta === "/cuenta") {
                ayudaDeEstaSeccion = "En Mi cuenta puedes actualizar tus datos y foto; tu rol y área los administra un administrador.";
            } else if (ruta === "/actividad") {
                ayudaDeEstaSeccion = "El registro de actividad permite revisar quién realizó cambios y cuándo.";
            } else if (ruta === "/avisos") {
                ayudaDeEstaSeccion = "Aquí puedes redactar comunicados, dirigirlos a un área y publicarlos u ocultarlos.";
            } else if (ruta.endsWith("/editar") && ruta.startsWith("/documentos/")) {
                ayudaDeEstaSeccion = "Al editar, guarda los metadatos correctos; el historial de versiones conserva las revisiones del archivo.";
            } else if (ruta === "/buscar") {
                ayudaDeEstaSeccion = "La búsqueda global encuentra documentos y expedientes por título, folio u oficio.";
            }

            const ayudaDeResultado = {
                subido: "Documento subido. Puedes encontrarlo en Biblioteca o vincularlo a un expediente.",
                editado: "Documento actualizado. Revisa su ficha para consultar la versión vigente.",
                eliminado: "Documento enviado a Papelera. Desde allí puedes restaurarlo si cambias de opinión.",
                restaurado: "Documento restaurado y disponible de nuevo en Biblioteca.",
                documentos_restaurados: "Selección restaurada. Ya puedes localizar los documentos en Biblioteca.",
                documentos_papelera: "Selección enviada a Papelera; los documentos se pueden restaurar.",
                eliminado_definitivo: "El documento se eliminó permanentemente y ya no se puede recuperar.",
                documentos_purgados: "Los documentos seleccionados se eliminaron permanentemente.",
                papelera_vacia: "La papelera quedó vacía; esa eliminación permanente no se puede deshacer.",
                expediente_creado: "Expediente creado con folio único. Ahora puedes abrirlo y vincular documentos.",
                documento_vinculado: "Documento vinculado. El original sigue disponible en Biblioteca.",
                documentos_vinculados: "Documentos vinculados al expediente; también siguen en Biblioteca.",
                expediente_eliminado: "Expediente eliminado. Sus documentos originales siguen en Biblioteca.",
                usuario_creado: "Cuenta creada. Verifica que su rol y área correspondan a sus responsabilidades.",
                usuario_editado: "Datos de usuario actualizados. Sus permisos dependen del rol y área asignados.",
                usuario_desactivado: "Cuenta desactivada; puedes volver a activarla desde su ficha.",
                usuario_activado: "Cuenta activada y habilitada para iniciar sesión.",
                usuario_eliminado: "Cuenta eliminada. El historial de actividad se conserva.",
                perfil_actualizado: "Perfil actualizado. Tus cambios de contacto ya están guardados.",
                password_cambiada: "Contraseña actualizada. Usa la nueva la próxima vez que inicies sesión.",
                aviso_creado: "Aviso publicado. Puedes dirigirlo a un área o a todos los usuarios.",
                aviso_estado: "Estado del aviso actualizado; revisa si quedó visible para los usuarios.",
                aviso_eliminado: "Aviso eliminado permanentemente.",
                formato: "Ese formato no está permitido. Elige uno de los formatos indicados junto al campo Archivo.",
                grande: "El archivo supera el límite de 20 MB. Reduce su tamaño e inténtalo otra vez.",
                categoria: "Selecciona una categoría válida antes de guardar el documento.",
                departamento: "Selecciona un área válida o deja el campo vacío si es opcional.",
                fecha: "Revisa que la fecha del documento sea válida.",
                foto_invalida: "La foto debe ser PNG o JPEG y no superar 5 MB.",
                password_corta: "La contraseña no cumple la longitud mínima indicada en el formulario."
            };
            const codigoAviso = new URLSearchParams(window.location.search).get("aviso");
            if (codigoAviso && ayudaDeResultado[codigoAviso]) {
                ayudaDeEstaSeccion = ayudaDeResultado[codigoAviso];
            }

            // Solo se inspeccionan controles visibles de la página actual.
            // Nunca se abre ni se lee el contenido de un archivo.
            const formularioDocumento = ruta === "/subir" ||
                (ruta.startsWith("/documentos/") && ruta.endsWith("/editar"));
            const formularioExpediente = ruta === "/expedientes/nuevo";
            const formularioGestion = ruta === "/usuarios";
            const guias = {
                "/subir": [
                    "Para registrar un documento, selecciona primero el archivo.",
                    "Completa título y categoría. Añade el número de oficio y la fecha si aparecen en el documento.",
                    "Revisa los datos y pulsa Subir documento. Después lo encontrarás en Biblioteca."
                ]
            };
            const guiaMensajeria = [
                "Aquí puedes conversar y compartir documentos con otros usuarios de NexusGrid.",
                "Para enviar un mensaje, adjunta un archivo o selecciona un documento de Biblioteca.",
                "Puedes buscar conversaciones en la lista. En escritorio está en el panel izquierdo.",
                "Los documentos de Biblioteca conservan sus restricciones de acceso al compartirlos.",
                "Las conversaciones con mensajes pendientes aparecen con un contador verde en la lista.",
                "Cerrar chat te devuelve a la lista y conserva tu borrador mientras sigas en Mensajería."
            ];
            let pasoGuia = 0;

            let ultimoConsejo = 0;
            let saludoPendiente = null;
            let esHabitual = false;
            const consejosMostrados = new Set();
            const dialogoConfirmacion = document.getElementById("dialogo-confirmacion");
            const dialogoBusqueda = document.getElementById("busqueda-asistida");
            let ultimaEscritura = 0;
            document.addEventListener("input", () => { ultimaEscritura = Date.now(); });
            const dialogoSelector = mensajeria && document.getElementById("mensajeria-selector");
            const dialogoOcupado = () => Boolean(dialogoConfirmacion?.open || dialogoBusqueda?.open ||
                dialogoSelector?.open || (textoMensaje && document.activeElement === textoMensaje) ||
                enviarMensaje?.getAttribute("aria-busy") === "true");
            // Las nuevas reacciones no deben activar sonidos del personaje.
            const animador = agente._animator;
            const nuevasReacciones = ["Greeting", "Wave"];
            if (typeof animador?._playSound === "function") {
                const reproducirSonido = animador._playSound.bind(animador);
                animador._playSound = (...args) => {
                    if (!nuevasReacciones.includes(animador.currentAnimationName)) reproducirSonido(...args);
                };
            }
            // La reacción va detrás del texto en la misma cola del motor; si el
            // usuario pide otro mensaje, stop() descarta la reacción pendiente.
            const reaccionar = nombre => {
                if (!nombre || movimientoReducido.matches || document.hidden || agente._hidden ||
                    !agente.hasAnimation(nombre) || typeof agente._addToQueue !== "function") return;
                const solicitada = Date.now();
                agente._addToQueue(siguiente => {
                    if (movimientoReducido.matches || document.hidden || agente._hidden || dialogoOcupado() || Date.now() - solicitada > 15000) {
                        siguiente();
                        return;
                    }
                    agente._playInternal(nombre, (_nombre, estado) => {
                        if (estado === clippy.Animator.States.EXITED) siguiente();
                    });
                });
            };
            movimientoReducido.addEventListener?.("change", evento => {
                if (evento.matches && ["Explain", "LookLeft", "Congratulate", ...nuevasReacciones].includes(agente._animator?.currentAnimationName)) {
                    agente._animator.exitAnimation();
                }
            });
            const decirConsejo = (texto, forzar = false, mantener = false) => {
                if (mensajeria || !texto || dialogoOcupado() || consejosMostrados.has(texto)) return false;
                if (!forzar && ultimaEscritura && Date.now() - ultimaEscritura < 3000) return false;
                if (!forzar && accionSaludo && !accionSaludo.hidden) return false;
                if (!forzar && Date.now() - ultimoConsejo < (esHabitual ? 20000 : 5000)) return false;
                consejosMostrados.add(texto);
                ultimoConsejo = Date.now();
                window.clearTimeout(saludoPendiente);
                agente.stop();
                agente.speak(texto, mantener);
                return true;
            };

            const aconsejarFormulario = (formulario, antesDeGuardar = false) => {
                if (!formulario || (!formularioDocumento && !formularioExpediente && !formularioGestion)) return;
                const tituloCampo = formulario.querySelector('[name="titulo"]');
                const categoriaCampo = formulario.querySelector('[name="categoria"]');
                const archivoCampo = formulario.querySelector('input[type="file"][name="archivo"]');
                const fechaCampo = formulario.querySelector('[name="fecha_documento"]');
                const oficioCampo = formulario.querySelector('[name="numero_oficio"]');
                if (antesDeGuardar) {
                    const faltantes = Array.from(formulario.querySelectorAll('[required]'))
                        .filter(campo => !campo.disabled && !String(campo.value || "").trim())
                        .map(campo => formulario.querySelector(`label[for="${campo.id}"]`)?.textContent?.trim() || campo.name);
                    if (faltantes.length) return `Antes de guardar, revisa: ${faltantes.slice(0, 3).join(", ")}.`;
                }
                if (fechaCampo?.value) {
                    const hoy = new Date();
                    const fechaLocal = `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, "0")}-${String(hoy.getDate()).padStart(2, "0")}`;
                    if (fechaCampo.value > fechaLocal) return "La fecha del documento es futura. Confirma que sea la fecha correcta.";
                }
                if (archivoCampo?.files?.length) {
                    const archivo = archivoCampo.files[0];
                    if (!/\.(pdf|docx|xlsx|txt|png|jpe?g|pptx)$/i.test(archivo.name)) return "El formato del archivo no aparece entre los permitidos. Revisa la extensión antes de guardar.";
                    if (archivo.size > 20 * 1024 * 1024) return "El archivo supera 20 MB. Elige uno más pequeño antes de guardar.";
                    if (!tituloCampo?.value.trim()) return "Archivo seleccionado. Falta escribir el título del documento.";
                    if (!categoriaCampo?.value) return "Archivo seleccionado. Elige una categoría antes de subirlo.";
                }
                if (oficioCampo?.value.trim() && !/[0-9]/.test(oficioCampo.value)) return "El número de oficio no contiene cifras. Comprueba que coincida con el documento.";
                if (formularioExpediente && antesDeGuardar && !tituloCampo?.value.trim()) return "Escribe el nombre del asunto antes de crear el expediente.";
                return null;
            };
            let avisoFormularioPendiente;
            document.addEventListener("change", (evento) => {
                if (!(evento.target instanceof HTMLElement)) return;
                const formulario = evento.target.closest("form");
                if (!formulario) return;
                window.clearTimeout(avisoFormularioPendiente);
                avisoFormularioPendiente = window.setTimeout(() => {
                    const consejo = aconsejarFormulario(formulario);
                    if (consejo) decirConsejo(consejo);
                    else if (evento.target.matches('input[type="file"][name="archivo"]') && evento.target.files?.length)
                        decirConsejo("Archivo seleccionado. Revisa título, categoría y fecha antes de guardarlo.");
                }, 350);
            });
            document.addEventListener("submit", (evento) => {
                const consejo = aconsejarFormulario(evento.target, true);
                if (consejo) decirConsejo(consejo, true);
            });
            let recordatorioCambios;
            let cambiosAvisados = false;
            document.addEventListener("input", (evento) => {
                const formulario = evento.target.closest?.("form");
                if (!formulario || (!formularioDocumento && !formularioExpediente)) return;
                window.clearTimeout(recordatorioCambios);
                if (!cambiosAvisados) recordatorioCambios = window.setTimeout(() => {
                    cambiosAvisados = true;
                    decirConsejo("Tienes datos sin guardar en este formulario. Revísalos antes de salir de la página.");
                }, 45000);
            });

            if (config.bibliotecaSinResultados) {
                ayudaDeEstaSeccion = "La búsqueda no encontró documentos visibles para tu cuenta. Prueba con menos filtros, el número de oficio o el año.";
            } else if (config.busquedaSinResultados) {
                ayudaDeEstaSeccion = "No hay resultados visibles para tu cuenta. Prueba el folio, el número de oficio o una parte del título.";
            } else if (config.discoLleno) {
                ayudaDeEstaSeccion = "El disco donde NexusGrid guarda archivos supera el 90 por ciento de uso. Avisa al administrador para revisar el espacio disponible.";
            }

            const detectarAccion = (evento) => {
                if (evento.type === "focusin" && !evento.target.matches("input, select, textarea, summary[data-clippy-tip]")) return;
                const control = evento.target.closest?.("[data-clippy-tip]");
                if (control && !control.closest("#dialogo-confirmacion")) {
                    decirConsejo(control.dataset.clippyTip);
                }
            };
            document.addEventListener("focusin", detectarAccion);
            document.addEventListener("change", detectarAccion);

            const lecturasProgramadas = new WeakMap();
            const programarLectura = (evento) => {
                if (mensajeria) return;
                const campo = evento.target;
                if (!(campo instanceof HTMLInputElement) || !campo.hasAttribute("data-clippy-read")) return;
                if (["password", "file", "hidden", "button", "submit", "checkbox", "radio"].includes(campo.type)) return;
                window.clearTimeout(lecturasProgramadas.get(campo));
                const temporizador = window.setTimeout(() => {
                    if (dialogoOcupado() || Date.now() - ultimaEscritura < 3000) return;
                    const valor = campo.value
                        .replace(/[\u0000-\u001f\u007f]/g, " ")
                        .replace(/\s+/g, " ")
                        .trim();
                    if (!valor) return;
                    const lectura = valor.length > 100 ? valor.slice(0, 97).trimEnd() + "…" : valor;
                    agente.stop();
                    agente.speak(`${campo.dataset.clippyRead}: ${lectura}`);
                }, 3000);
                lecturasProgramadas.set(campo, temporizador);
            };
            document.addEventListener("input", programarLectura);
            document.addEventListener("change", programarLectura);

            const personaje = document.querySelector(".clippy");
            if (personaje) {
                personaje.setAttribute("role", "button");
                personaje.setAttribute("aria-label", "Clippy. Pulsa para pedir ayuda.");
                personaje.setAttribute("tabindex", "0");
                personaje.addEventListener("mouseenter", () => {
                    window.clearTimeout(temporizadorInactivo);
                    personaje.classList.remove("clippy-inactivo");
                });
                personaje.addEventListener("mouseleave", () => programarReposo());
                personaje.addEventListener("focus", () => {
                    window.clearTimeout(temporizadorInactivo);
                    personaje.classList.remove("clippy-inactivo");
                });
                personaje.addEventListener("blur", () => programarReposo());
                const hablar = () => {
                    if (mensajeria && (dialogoOcupado() || !ubicar())) return;
                    agente.stop();
                    const guia = mensajeria ? guiaMensajeria : guias[ruta];
                    if (guia) {
                        agente.speak(mensajeria ? guia[pasoGuia] :
                            `Guía, paso ${pasoGuia + 1} de ${guia.length}. ${guia[pasoGuia]} Pulsa de nuevo para continuar.`);
                        pasoGuia = (pasoGuia + 1) % guia.length;
                    } else {
                        agente.speak(ayudaDeEstaSeccion + " Enfoca un campo o marca una opción y te daré un consejo relacionado.");
                    }
                    const exitos = ["subido", "editado", "restaurado", "documentos_restaurados", "expediente_creado"];
                    reaccionar(config.bibliotecaSinResultados || config.busquedaSinResultados
                        ? "LookLeft" : exitos.includes(codigoAviso) ? "Congratulate" :
                            agente.hasAnimation("Wave") ? "Wave" : "Explain");
                };
                personaje.addEventListener("click", hablar);
                personaje.addEventListener("keydown", (evento) => {
                    if (evento.key === "Enter" || evento.key === " ") {
                        evento.preventDefault();
                        hablar();
                    }
                });
            }

            window.sigedClippyPreferencias?.then(preferencias => {
                if (mensajeria) return;
                esHabitual = preferencias?.experiencia === "habitual";
                const seccionFrecuente = preferencias?.secciones?.[0];
                const nombresSeccion = { biblioteca: "Biblioteca", expedientes: "Expedientes", subir: "Subir documento", buscar: "Búsqueda global", papelera: "Papelera" };
                if (esHabitual && nombresSeccion[seccionFrecuente] && seccionFrecuente !== ruta.slice(1)) {
                    ayudaDeEstaSeccion += ` Sueles usar ${nombresSeccion[seccionFrecuente]}; puedes abrirla desde el menú lateral.`;
                }
                const esEntrada = config.saludoEntrada;
                if (!esEntrada) return;
                const nombre = config.nombre;
                const aperturas = [`¡Hola, ${nombre}!`, `¡Buen día, ${nombre}!`, `¡Qué tal, ${nombre}!`, `¡Bienvenido, ${nombre}!`];
                const apertura = aperturas[(new Date().getDate() + config.usuarioId) % aperturas.length];
                const rutas = { inicio: "/inicio", biblioteca: "/", buscar: "/buscar", expedientes: "/expedientes", cuenta: "/cuenta",
                    ...(config.puedeSubir ? { subir: "/subir" } : {}),
                    ...(config.puedeRestaurar ? { papelera: "/papelera" } : {}),
                    ...(config.puedeUsuarios ? { usuarios: "/usuarios" } : {}),
                    ...(config.puedeActividad ? { actividad: "/actividad" } : {})
                };
                let texto = `${apertura} ¿Abrimos la Biblioteca?`;
                let etiqueta = "Ir a Biblioteca";
                let destino = "/";
                if (config.discoLleno) {
                    texto = `${apertura} El disco está casi lleno. ¿Lo revisamos?`;
                    etiqueta = "Ver almacenamiento";
                    destino = "/inicio#almacenamiento-titulo";
                } else {
                    const rutina = preferencias?.rutina;
                    const ultimaFicha = preferencias?.expediente_reciente;
                    if (rutina && rutas[rutina] && rutina !== "inicio") {
                        texto = `${apertura} Sueles abrir ${nombresSeccion[rutina] || rutina}. ¿Vamos?`;
                        etiqueta = "Ir ahí";
                        destino = rutas[rutina];
                    } else if (ultimaFicha?.id) {
                        texto = `${apertura} ¿Seguimos en el expediente ${ultimaFicha.folio || ultimaFicha.id}?`;
                        etiqueta = "Continuar";
                        destino = `/expedientes/${ultimaFicha.id}`;
                    } else if (preferencias?.dias_sin_entrar >= 7 && rutas[seccionFrecuente]) {
                        texto = `${apertura} ¿Volvemos a ${nombresSeccion[seccionFrecuente] || "tu sección habitual"}?`;
                        etiqueta = "Ir";
                        destino = rutas[seccionFrecuente];
                    } else if (!esHabitual && config.puedeSubir) {
                        texto = `${apertura} ¿Te muestro cómo subir un documento?`;
                        etiqueta = "Ver guía";
                        destino = rutas.subir || "/";
                    }
                }
                saludoPendiente = window.setTimeout(() => {
                    if (!decirConsejo(texto, false, true)) return;
                    reaccionar("Greeting");
                    if (accionSaludo) {
                        accionSaludo.textContent = etiqueta;
                        accionSaludo.href = destino;
                        accionSaludo.hidden = false;
                    }
                    programarCierreSaludo(35000);
                }, 3000);
            });
        }, (error) => {
            console.warn("No se pudo cargar el asistente Clippy.", error);
        });
    }

    if (document.readyState === "complete") cargarAsistente();
    else window.addEventListener("load", cargarAsistente, { once: true });
})();
