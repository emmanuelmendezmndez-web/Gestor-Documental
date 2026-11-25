// Clasifica intenciones; no aplica propuestas ni responde preguntas.
((raiz) => {
    const contextual = typeof module !== 'undefined' && module.exports
        ? require('./interprete_contextual.js') : raiz.sigedInterpretarContexto;
    const normalizar = texto => texto.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[¿?¡!.,;:]/g, ' ').replace(/\s+/g, ' ').trim();
    const temas = [
        ['permisos', /\b(?:permiso|permisos|autorizacion|acceso|por que no puedo)\b/],
        ['vincular_documentos', /\b(?:vincular|vinculo|vincularlos|asociar)\b/],
        ['gestionar_expedientes', /\b(?:crear|creo|crear un|creacion)\b.*\bexpedientes?\b/],
        ['restaurar', /\b(?:restaurar|restauro|recuperar|recupero)\b/],
        ['eliminar_definitivamente', /\b(?:eliminar|elimino|borrar|borro)\b.*\b(?:definitiv\w*|permanent\w*)\b/],
        ['papelera', /\bpapelera\b/],
        ['usuarios', /\b(?:usuarios?|cuentas?|dar de alta|dar de baja)\b/],
        ['subida', /\b(?:subir|subo|subida|cargar|cargo)\b/],
        ['busqueda', /\b(?:buscar|busco|busqueda|encuentro|encontrar|localizar|localizo)\b/],
        ['biblioteca', /\bbiblioteca\b/],
        ['expedientes', /\bexpedientes?\b/],
        ['inicio', /\b(?:inicio|panel principal|indicadores|accesos rapidos)\b/],
        ['documentos', /\b(?:ficha|metadatos|vista previa|previsualiz\w*|documentos?)\b/],
        ['editar', /\b(?:editar|edito|modificar|actualizar)\b.*\b(?:documento|archivo|metadatos)\b/],
        ['descargar', /\b(?:descargar|descargo|descarga)\b/],
        ['mensajeria', /\b(?:mensajeria|mensajes?|conversaciones?|chat|campana|notificaciones?)\b/],
        ['avisos', /\b(?:avisos?|comunicados?|publicaciones?)\b/],
        ['gestionar_avisos', /\b(?:cre\w+|public\w+|ocult\w+|edit\w+|configur\w+|vencimiento|duracion)\b.*\b(?:avisos?|comunicados?)\b|\b(?:avisos?|comunicados?)\b.*\b(?:vencimiento|duracion)\b/],
        ['actividad', /\b(?:actividad|auditoria|registro de operaciones|trazabilidad)\b/],
        ['almacenamiento', /\b(?:almacenamiento|disco|espacio libre|capacidad)\b/],
        ['ajustes', /\b(?:ajustes|preferencias|tema|modo oscuro|clippy|habitos)\b/],
        ['cuenta', /\b(?:mi cuenta|mi perfil|mi contrasena|foto de perfil)\b/],
        ['sesion_general', /\b(?:sesion|credenciales)\b/],
        ['errores', /\b(?:error|problema|fallo)\b/]
    ];
    const acciones = [
        ['eliminar', /\b(?:elimin\w*|borr\w*|vaci\w*)\b.*\b(?:definitiv\w*|permanent\w*|papelera)\b/],
        ['papelera', /\b(?:enviar|mover|mandar)\b.*\bpapelera\b/],
        ['restaurar', /\b(?:restaur\w*|recuper\w*)\b/],
        ['subir', /\b(?:subir|subo|cargar|cargo|subida)\b/],
        ['editar', /\b(?:edit\w*|modific\w*)\b.*\b(?:document\w*|archivo\w*|metadatos)\b/],
        ['descargar', /\b(?:descarg\w*)\b/],
        ['gestionar_expedientes', /\b(?:cre\w+|vincul\w+|gestion\w+)\b.*\bexpedientes?\b/],
        ['avisos', /\b(?:public\w+|cre\w+|administr\w+)\b.*\b(?:avisos?|comunicados?)\b/],
        ['usuarios', /\b(?:cre\w+|administr\w+|gestion\w+)\b.*\b(?:usuarios?|cuentas?)\b/],
        ['actividad', /\b(?:actividad|auditoria)\b/],
    ];
    function diagnostico(texto) {
        const registro = texto.match(/\b(?:registro(?: interno)?|documento(?: numero)?|archivo(?: numero)?)\s+([1-9]\d{0,17})\b/)?.[1];
        const permiso = /\b(?:tengo (?:permiso|acceso)|mi rol|mis permisos|mi cuenta puede|que (?:permisos tengo|puedo hacer)|por que no puedo)\b/.test(texto);
        if (permiso) {
            const accion = acciones.find(([, regla]) => regla.test(texto))?.[0];
            if ((accion && (!registro || /\bpermiso\b/.test(texto))) ||
                /\b(?:mi rol|mis permisos|que permisos tengo|que puedo hacer)\b/.test(texto)) {
                return {tipo:'diagnostico', tema:'permisos', accion};
            }
        }
        if (/\b(?:sistema|servidor|mensajeria|chat)\b/.test(texto) &&
            /\b(?:estado|funcion\w*|caid\w*|disponib\w*|operativ\w*|no carga|habilitad\w*)\b/.test(texto) &&
            !/^como funciona\b/.test(texto)) {
            return {tipo:'diagnostico', tema:/\b(?:mensajeria|chat)\b/.test(texto) ? 'mensajeria' : 'sistema'};
        }
        if (/\b(?:espacio|disco|almacenamiento|capacidad)\b/.test(texto) &&
            /\b(?:cuanto|cuanta|queda|libre|lleno|disponib\w*|ocupad\w*)\b/.test(texto)) return {tipo:'diagnostico', tema:'almacenamiento'};
        if (/\b(?:documentos?|archivos?|registro interno)\b/.test(texto) &&
            /\b(?:no aparece|no encuentro|no puedo abrir|no puedo descargar|no se abre|disponib\w*|comprueb\w*|verific\w*)\b/.test(texto)) {
            return {tipo:'diagnostico', tema:'documento', registro};
        }
        return null;
    }
    function ayudaSesion(texto) {
        const consultaDocumento = /^(?:(?:me )?(?:puedes|podrias|ayudas a) )?(?:busc\w*|localiz\w*|muestr\w*|ense\w*|encuentr\w*)\b.*\b(?:manual|guia|documentos?|archivos?|instructivo|oficio)\b/;
        if (consultaDocumento.test(texto)) return null;
        const credencial = /\b(?:contrasena|clave|password)\b/.test(texto);
        if (credencial && (/\b(?:olvide|olvidada|olvidado|no recuerdo|no me acuerdo|perdi|se me olvido)\b/.test(texto) ||
                (/\b(?:recuper\w*|restablec\w*|reinici\w*)\b/.test(texto) && /\b(?:mi|mi acceso|para entrar|para ingresar)\b/.test(texto)))) {
            return 'contrasena_olvidada';
        }
        if (/\bsesion\b/.test(texto) && /\b(?:caduc\w*|expir\w*|venc\w*)\b/.test(texto)) return 'sesion';
        if (/\b(?:(?:cerr\w*|cierr\w*|termin\w*|finaliz\w*) (?:de |la |mi )?sesion|(?:salgo|salir|salga|desconectarme|desconecto) (?:de |del )?(?:mi cuenta|sesion|gestor)|logout)\b/.test(texto)) return 'cerrar_sesion';
        if (/\b(?:inici\w* (?:la |mi )?sesion|(?:entr\w*|ingres\w*|acced\w*) (?:a |en )mi cuenta|login)\b/.test(texto)) return 'iniciar_sesion';
        return null;
    }
    function clasificar(entrada, contexto = {}, interpretar = contextual) {
        if (typeof entrada !== 'string' || !entrada.trim()) return {tipo:'aclaracion', motivo:'entrada_vacia', alternativas:['ayuda','busqueda']};
        const texto = normalizar(entrada).replace(/^(?:(?:oye|ey|clippy|clipy|hola) )+/, '');
        const sesion = ayudaSesion(texto);
        if (sesion) return {tipo:'ayuda', tema:sesion};
        // El contexto vacío permite reconocer también órdenes que requieren aclaración.
        const estado = contexto?.estado || {filtros:{}};
        if (typeof interpretar === 'function') {
            const resultado = interpretar(entrada, {estado, categorias:contexto?.categorias || [], areas:contexto?.areas || []});
            if (resultado.tipo !== 'consulta_nueva') return {tipo:'correccion_contextual'};
        }
        if (/\b(?:formato no permitido|extension no permitida|formatos? (?:acept\w*|admit\w*|permit\w*))\b/.test(texto)) {
            return {tipo:'ayuda', tema:'formato_subida'};
        }
        if (/\b(?:archivo (?:demasiado grande|vacio)|supera (?:el )?(?:maximo|limite)|cuanto puede pesar)\b/.test(texto)) {
            return {tipo:'ayuda', tema:'limite_subida'};
        }
        const pideTotal = !/^(?:como|por que)\b/.test(texto) &&
            /\b(?:cuantos|cuantas|total|cantidad)\b|^cuenta\b/.test(texto) &&
            !/\b(?:puedo|puede|permite|admite)\b/.test(texto);
        if (pideTotal) {
            if (/\b(?:documentos|archivos|oficios|actas|contratos|informes|pdfs?)\b/.test(texto)) {
                return {tipo:'ayuda', tema:'conteo_documentos'};
            }
            if (/\b(?:expedientes|usuarios|mensajes|avisos|comunicados|registros)\b/.test(texto)) {
                return {tipo:'ayuda', tema:'conteo_no_disponible'};
            }
        }
        const comprobacion = diagnostico(texto);
        if (comprobacion) return comprobacion;
        const explicita = /^(?:como|por que|para que|cual es|cuales son|donde|que|necesito ayuda|ayuda|puedo|puede|se puede|es posible|explicame|dime como|me explicas|(?:me )?puedes explicar)\b/.test(texto);
        if (!explicita) {
            const documental = /^(?:(?:el|la|los|las|un|una|mis) )?(?:documentos?|archivos?|contratos?|actas?|informes?|oficios?|certificados?|inventarios?|bitacoras?|comunicados?|folios?|expedientes?)\b/.test(texto);
            const consulta = /^(?:busca(?:r|me)?|localiza(?:r|me)?|encuentra(?:me)?|ubica(?:r|me)?)\b/.test(texto);
            const referencia = /\b[\w-]+\.(?:pdf|docx?|xlsx?|pptx?|txt|csv|jpe?g|png|webp|zip)\b|\b[a-z]{2,12}[-/]\d+[-/][a-z0-9-]+\b/i.test(entrada);
            return documental || consulta || referencia ? {tipo:'busqueda_documental'}
                : {tipo:'aclaracion', motivo:'intencion_ambigua', alternativas:['ayuda','busqueda']};
        }
        const hallados = temas.filter(([, regla]) => regla.test(texto)).map(([tema]) => tema);
        if (hallados.includes('permisos')) return {tipo:'ayuda', tema:'permisos'};
        // «Recuperar de la papelera» y «vincular a un expediente» son un solo propósito.
        const secundarios = {
            papelera: ['restaurar', 'eliminar_definitivamente'],
            expedientes: ['vincular_documentos', 'gestionar_expedientes'],
            avisos: ['gestionar_avisos'], usuarios: ['cuenta'],
            documentos: hallados.filter(tema => tema !== 'documentos' && tema !== 'errores'),
            errores: hallados.filter(tema => tema !== 'errores'),
        };
        const especificos = hallados.filter(tema => !secundarios[tema]?.some(otro => hallados.includes(otro)));
        if (especificos.length === 1) return {tipo:'ayuda', tema:especificos[0]};
        return {tipo:'aclaracion', motivo:especificos.length ? 'varios_temas' : 'intencion_ambigua', alternativas:especificos.length ? especificos : ['ayuda','busqueda']};
    }
    if (typeof module !== 'undefined' && module.exports) module.exports = clasificar;
    else raiz.sigedClasificarAyuda = clasificar;
})(globalThis);
