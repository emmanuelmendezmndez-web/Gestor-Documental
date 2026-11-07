// Interpretación sin efectos: la aplicación de cada propuesta corresponde al llamador.
((raiz) => {
    const normalizar = texto => texto.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim().replace(/\s+/g, ' ');
    const meses = 'enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre';
    const aclarar = motivo => ({tipo: 'aclaracion', motivo});

    // contexto contiene el estado copiado de memoria y los catálogos disponibles.
    function interpretarContexto(instruccion, contexto, detallar = raiz.sigedInterpretarBusqueda?.detallar) {
        if (typeof instruccion !== 'string' || !instruccion.trim()) return aclarar('instruccion_vacia');
        const texto = normalizar(instruccion).replace(/[.!?¿¡]+$/g, '').trim();
        if (/^(empieza|comienza) de nuevo$/.test(texto)) return {tipo: 'reiniciar'};
        if (!contexto || !contexto.estado || !contexto.estado.filtros) return aclarar('sin_contexto');
        const {filtros} = contexto.estado;
        if (/^(olvida|quita|quitar|elimina|eliminar|borra|borrar) (todos )?(los )?filtros$/.test(texto)) return {tipo: 'limpiar_filtros'};
        if (/^conserva (la )?categoria$/.test(texto)) return {tipo: 'cambios', cambios: {}, explicitos: [], conservar: ['categoria']};
        if (/\b(?:quita|quitar|elimina|eliminar|borra|borrar|conserva|mant[ée]n|olvida|empieza|comienza)\b/.test(texto) && /\b(?:y|pero|excepto|ademas)\b/.test(texto)) return aclarar('instruccion_compuesta');
        if (/^(?:quita|quitar|elimina|eliminar|borra|borrar)$/.test(texto)) return aclarar('filtro_no_identificado');
        const quitar = texto.match(/^(?:quita|quitar|elimina|eliminar|borra|borrar) (?:el |la |los |las )?(.+)$/);
        if (quitar) {
            const objetivo = quitar[1];
            const campos = {categoria:'categoria', departamento:'departamento', area:'departamento', fechas:'fechas', fecha:'fechas', oficio:'oficio', autor:'autor', busqueda:'buscar'};
            let campo = campos[objetivo];
            if (!campo) {
                const encontrados = ['categoria', 'departamento', 'oficio', 'autor', 'buscar'].filter(c => filtros[c] && normalizar(filtros[c]) === objetivo);
                if (!filtros.departamento && (contexto.areas || []).some(area => normalizar(area) === objetivo)) encontrados.push('departamento');
                if (encontrados.length !== 1) return aclarar('filtro_no_identificado');
                campo = encontrados[0];
            }
            const claves = campo === 'fechas' ? ['desde', 'hasta'] : [campo];
            if (!claves.some(c => filtros[c])) return aclarar('filtro_inexistente');
            return {tipo:'cambios', cambios:Object.fromEntries(claves.map(c => [c, ''])), explicitos:claves, conservar:[]};
        }
        const correccion = texto.match(/^mejor\s+(?:(?:busca|buscar)\s+|(?:de|del)\s+)?(.+)$/);
        if (!correccion) return {tipo:'consulta_nueva', consulta:instruccion.trim()};
        if (typeof detallar !== 'function') return aclarar('interprete_no_disponible');
        let contenido = correccion[1];
        const mesSolo = contenido.match(new RegExp(`^(${meses})$`));
        if (mesSolo) {
            const desde = filtros.desde, hasta = filtros.hasta;
            if (!/^\d{4}-\d{2}-\d{2}$/.test(desde || '') || !/^\d{4}-\d{2}-\d{2}$/.test(hasta || '') || desde.slice(0, 4) !== hasta.slice(0, 4) || desde > hasta) return aclarar('anio_ambiguo');
            contenido += ` de ${desde.slice(0, 4)}`;
        }
        const resultado = detallar(contenido, contexto.categorias || [], contexto.areas || []);
        if (resultado.avisos.length || resultado.dudas.length || resultado.expediente) return aclarar('interpretacion_ambigua');
        const cambios = resultado.filtros;
        const claves = Object.keys(cambios);
        // Una corrección debe identificar un único criterio, o un intervalo completo.
        if (!claves.length || (claves.length > 1 && !(claves.length === 2 && claves.includes('desde') && claves.includes('hasta'))) || (claves.includes('buscar') && !/^mejor\s+(?:busca|buscar)\s+/.test(texto))) return aclarar('criterio_ambiguo');
        return {tipo:'cambios', cambios:{...cambios}, explicitos:claves, conservar:[]};
    }
    if (typeof module !== 'undefined' && module.exports) module.exports = interpretarContexto;
    else raiz.sigedInterpretarContexto = interpretarContexto;
})(globalThis);
