// Las capacidades personalizan el texto; el servidor autoriza cada operación.
((raiz) => {
    const orientacion = 'Consulta con una persona administradora para obtener orientación sobre esta función.';
    // Pantallas desde las que se admite consultar el catálogo. Es independiente
    // de las pantallas donde se realiza cada acción descrita en una ayuda.
    const pantallasReconocidas = ['inicio', 'biblioteca', 'buscar', 'subir', 'expedientes', 'expediente_nuevo', 'expediente', 'papelera', 'usuarios', 'cuenta', 'actividad', 'documentos', 'mensajeria', 'avisos', 'ajustes'];
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
        usuarios: {pantallas:['usuarios'], capacidades:['ver', 'usuarios'], respuesta:'Abre Nuevo usuario desde Usuarios. En el formulario asigna únicamente el rol y el área necesarios para sus tareas.'},
        permisos: {capacidades:['ver'], respuesta:'Las acciones disponibles dependen de tu cuenta. El rol habilita acciones y el área limita qué documentos puedes consultar. Para revisar una acción concreta, pregunta, por ejemplo: «¿Tengo permiso para subir documentos?».'},
        inicio: {capacidades:['ver'], respuesta:'Inicio reúne indicadores, comunicados visibles para tu cuenta, documentos recientes y accesos rápidos. El indicador de estado distingue entre Operativo, Funcionamiento degradado y Estado crítico.'},
        documentos: {capacidades:['ver'], respuesta:'Abre el título de un documento en Biblioteca para ver su ficha, registro interno y metadatos. Cuando el formato y el archivo lo permitan, la ficha ofrece vista previa.'},
        editar: {capacidades:['editar'], respuesta:'En la ficha del documento, abre Editar y revisa los metadatos antes de guardar. Si el botón no aparece, comprueba el acceso a ese documento con Administración.'},
        descargar: {capacidades:['descargar'], respuesta:'Abre la ficha o la fila del documento en Biblioteca y pulsa Descargar. Si el archivo no está disponible, comparte el número de registro con Administración.'},
        mensajeria: {capacidades:['ver'], respuesta:'Cuando Mensajería está habilitada, abre Mensajes y elige Nueva conversación o una conversación existente. Puedes adjuntar archivos o compartir documentos desde Biblioteca. Los documentos compartidos conservan sus permisos. La campana muestra los avisos de mensajes.'},
        avisos: {capacidades:['ver'], respuesta:'En Inicio, Avisos y comunicados muestra publicaciones vigentes para todos o para tu departamento. Los avisos ocultos, vencidos o dirigidos a otra área quedan fuera de esa lista.'},
        gestionar_avisos: {capacidades:['avisos'], respuesta:'Desde Inicio, pulsa Administrar en Avisos y comunicados. Puedes redactar el aviso, elegir el departamento y la duración, y publicarlo o guardarlo oculto.'},
        actividad: {capacidades:['actividad'], respuesta:'En Actividad puedes consultar el registro de operaciones, filtrar la lista y revisar fecha, usuario, acción y resultado.'},
        almacenamiento: {capacidades:['ver'], respuesta:'En Inicio, Almacenamiento en disco muestra el espacio ocupado, libre y total de la unidad documental. Puedes preguntar «¿Cuánto espacio queda?» para consultar la capacidad.'},
        ajustes: {capacidades:['ver'], respuesta:'Abre Ajustes entre tu perfil y Cerrar sesión. Puedes elegir tema claro, oscuro o automático, mostrar u ocultar Clippy y controlar sus consejos y el registro de hábitos. Pulsa Guardar ajustes.'},
        cuenta: {capacidades:['ver'], respuesta:'Abre tu perfil para cambiar tus datos, foto o contraseña. Los cambios de rol y departamento corresponden a Administración.'},
        sesion: {capacidades:['ver'], respuesta:'Si el formulario indica que la sesión caducó, recarga la página y vuelve a iniciar sesión si se solicita. Si el problema continúa, indica en qué pantalla ocurre y copia el mensaje exacto.'},
        formato_subida: {capacidades:['subir'], respuesta:'Subir documento admite PDF, DOCX, XLSX, TXT, PNG, JPG, JPEG y PPTX. Comprueba la extensión y que el archivo sea del formato indicado.'},
        limite_subida: {capacidades:['subir'], respuesta:'El límite de Subir documento es 20 MB por archivo. Comprueba su tamaño y que el archivo tenga contenido. Si está dentro del límite, indica el mensaje exacto.'},
        errores: {capacidades:['ver'], respuesta:'Indica la pantalla, la acción y el mensaje exacto. Para un archivo concreto, incluye su número de registro. Omite contraseñas y contenido confidencial.'}
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
