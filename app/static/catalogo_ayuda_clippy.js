// Las capacidades personalizan el texto; el servidor autoriza cada operación.
((raiz) => {
    const orientacion = 'Consulta con una persona administradora para obtener orientación sobre esta función.';
    // Pantallas desde las que se admite consultar el catálogo. Es independiente
    // de las pantallas donde se realiza cada acción descrita en una ayuda.
    const pantallasReconocidas = ['inicio', 'biblioteca', 'buscar', 'subir', 'expedientes', 'expediente_nuevo', 'expediente', 'papelera', 'usuarios', 'cuenta', 'actividad'];
    // `pantallas` identifica el destino de la ayuda; no restringe dónde se pregunta.
    const catalogo = Object.freeze({
        biblioteca: {pantallas:['biblioteca'], capacidades:['ver'], respuesta:'En Biblioteca abre Buscar y filtrar para combinar título, categoría, área o fechas.'},
        busqueda: {pantallas:['buscar', 'biblioteca'], capacidades:['ver', 'ver_expedientes'], respuesta:'Escribe el título, folio o número de oficio en la barra superior y pulsa Buscar. En Biblioteca usa Buscar y filtrar para precisar los resultados.'},
        subida: {pantallas:['subir'], capacidades:['ver', 'subir'], respuesta:'Abre Subir documento desde el menú, completa título y categoría y selecciona un archivo permitido de hasta 20 MB. Si no tienes área asignada, consulta a una persona administradora.'},
        expedientes: {pantallas:['expedientes', 'expediente'], capacidades:['ver', 'ver_expedientes'], respuesta:'Abre Expedientes desde el menú lateral y abre una carpeta para consultar el asunto y sus documentos visibles.'},
        gestionar_expedientes: {pantallas:['expedientes', 'expediente_nuevo'], capacidades:['ver', 'ver_expedientes', 'gestionar_expedientes'], respuesta:'En Expedientes pulsa Nuevo expediente, escribe el nombre o asunto y, si deseas, una descripción. Al crearlo se asigna el folio.'},
        vincular_documentos: {pantallas:['expediente'], capacidades:['ver', 'ver_expedientes', 'gestionar_expedientes'], respuesta:'Abre la ficha del expediente, busca documentos, selecciona los que correspondan y pulsa Vincular selección al expediente.'},
        papelera: {pantallas:['papelera'], capacidades:['ver', 'papelera'], respuesta:'Abre Papelera desde el menú para consultar los documentos que ya no aparecen en Biblioteca.'},
        restaurar: {pantallas:['papelera'], capacidades:['ver', 'papelera', 'restaurar'], respuesta:'En Papelera selecciona los documentos y pulsa Restaurar selección para devolverlos a Biblioteca.'},
        eliminar_definitivamente: {pantallas:['papelera'], capacidades:['ver', 'papelera', 'eliminar'], respuesta:'En Papelera puedes seleccionar documentos y elegir Eliminar selección definitivamente. Esta acción no se puede deshacer.'},
        usuarios: {pantallas:['usuarios'], capacidades:['ver', 'usuarios'], respuesta:'En Usuarios completa Crear usuario y asigna únicamente el rol y el área necesarios para sus tareas.'},
        permisos: {capacidades:['ver'], respuesta:'Las acciones disponibles dependen de tu cuenta. Consulta a una persona administradora si necesitas acceso.'}
    });

    function consultar(tema, contexto) {
        if (typeof tema !== 'string' || !Object.hasOwn(catalogo, tema)) return orientacion;
        const ayuda = catalogo[tema];
        if (!contexto || !pantallasReconocidas.includes(contexto.pantalla)) return orientacion;
        const capacidades = contexto.capacidades;
        if (!capacidades || typeof capacidades !== 'object' || Array.isArray(capacidades) ||
            !ayuda.capacidades.every(clave => Object.hasOwn(capacidades, clave) && capacidades[clave] === true)) return orientacion;
        return ayuda.respuesta;
    }
    if (typeof module !== 'undefined' && module.exports) module.exports = consultar;
    else raiz.sigedConsultarAyuda = consultar;
})(globalThis);
