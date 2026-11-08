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
        ['usuarios', /\b(?:usuarios?|cuentas?)\b/],
        ['subida', /\b(?:subir|subo|subida|cargar|cargo)\b/],
        ['busqueda', /\b(?:buscar|busco|busqueda|encuentro|encontrar|localizar|localizo)\b/],
        ['biblioteca', /\bbiblioteca\b/],
        ['expedientes', /\bexpedientes?\b/]
    ];
    function clasificar(entrada, contexto = {}, interpretar = contextual) {
        if (typeof entrada !== 'string' || !entrada.trim()) return {tipo:'aclaracion', motivo:'entrada_vacia', alternativas:['ayuda','busqueda']};
        const texto = normalizar(entrada);
        // El contexto vacío permite reconocer también órdenes que requieren aclaración.
        const estado = contexto?.estado || {filtros:{}};
        if (typeof interpretar === 'function') {
            const resultado = interpretar(entrada, {estado, categorias:contexto?.categorias || [], areas:contexto?.areas || []});
            if (resultado.tipo !== 'consulta_nueva') return {tipo:'correccion_contextual'};
        }
        const explicita = /^(?:como|por que|cual es|cuales son|donde|que hago|que significa|necesito ayuda|ayuda|puedo|puede|se puede)\b/.test(texto);
        if (!explicita) return {tipo:'busqueda_documental'};
        const hallados = temas.filter(([, regla]) => regla.test(texto)).map(([tema]) => tema);
        if (hallados.includes('permisos')) return {tipo:'ayuda', tema:'permisos'};
        // «Recuperar de la papelera» y «vincular a un expediente» son un solo propósito.
        const especificos = hallados.filter(tema => !(tema === 'papelera' && (hallados.includes('restaurar') || hallados.includes('eliminar_definitivamente'))) && !(tema === 'expedientes' && (hallados.includes('vincular_documentos') || hallados.includes('gestionar_expedientes'))));
        if (especificos.length === 1) return {tipo:'ayuda', tema:especificos[0]};
        return {tipo:'aclaracion', motivo:especificos.length ? 'varios_temas' : 'intencion_ambigua', alternativas:especificos.length ? especificos : ['ayuda','busqueda']};
    }
    if (typeof module !== 'undefined' && module.exports) module.exports = clasificar;
    else raiz.sigedClasificarAyuda = clasificar;
})(globalThis);
