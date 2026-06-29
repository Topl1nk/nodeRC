# NodeRC

![Screenshot](images/Screenshot.png)

[English](../README.md) | [Українська](README.uk.md) | [Español](README.es.md) | [中文](README.zh.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [日本語](README.ja.md) | [हिन्दी](README.hi.md) | [Português](README.pt.md) | [العربية](README.ar.md)

NodeRC es una interfaz visual y editor basado en nodos no oficial para los comandos de la CLI de RealityCapture / RealityScan. Escrito en Python utilizando PyQt5, el proyecto te permite conectar y gestionar visualmente nodos de comandos en un lienzo interactivo, proporcionando una interfaz cómoda para la automatización de flujos de trabajo.

## Características

- **Lienzo interactivo (Canvas):** Un espacio de trabajo infinito con soporte para desplazamiento y zoom.
- **Arquitectura de nodos:** Varios tipos de nodos que soportan conexiones entrantes y salientes (sockets).
- **Conexiones dinámicas:** Enlace visual de puertos de ejecución y puertos de datos.
- **Sistema de configuración:** Colores, tamaños y estilos personalizables a través de un archivo de configuración centralizado.
- **Menú de búsqueda:** Un menú conveniente para agregar rápidamente nuevos nodos al lienzo.

## Requisitos

- Python 3.7+
- PyQt5

## Instalación

1. Clona el repositorio:

   ```bash
   git clone <URL_del_repositorio>
   cd nodeRC
   ```

2. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```

## Uso

Para iniciar el editor, ejecuta:

```bash
python nodeRC.py
```

### Controles y atajos

- **Desplazar el lienzo:** Mantén presionado el **botón central del ratón (MMB)** y arrastra.
- **Zoom:** Usa la **rueda del ratón**.
- **Agregar nodo:** Presiona la tecla **Espacio** o haz **clic derecho** en un espacio vacío para abrir el menú de búsqueda. Selecciona un nodo de comando o parámetro.
- **Conectar sockets:** Arrastra una línea desde un socket de salida a un socket de entrada compatible.
  - Si arrastras desde un socket y lo sueltas en un espacio vacío del lienzo, se abrirá el menú de búsqueda para añadir y conectar automáticamente un nuevo nodo.
- **Eliminar nodo/conexión:** Selecciona el elemento y presiona **Suprimir** (Delete).
- **Agrupar nodos:** Selecciona los nodos y presiona **Ctrl + G** para enmarcarlos.
- **Duplicar nodos:** Selecciona los nodos y presiona **Ctrl + D**.
- **Copiar y pegar:** Selecciona los nodos y presiona **Ctrl + C** para copiar, y **Ctrl + V** para pegar en la posición del cursor.
- **Deshacer / Rehacer:** Presiona **Ctrl + Z** para deshacer y **Ctrl + Y** (o **Ctrl + Shift + Z**) para rehacer.
- **Seleccionar todo:** Presiona **Ctrl + A**.
- **Mostrar/Ocultar cuadrícula:** Presiona la tecla **G**.
- **Ajustar vista:** Presiona la tecla **F** para centrar la vista en la selección (o en todos los nodos si no hay selección).
- **Renombrar nodo:** Selecciona un nodo de parámetro y presiona **F2**.
- **Pantalla completa:** Presiona **F11** para alternar el modo de pantalla completa.

### Flujo de ejecución

1. **Iniciar la cadena:** El nodo `> START` siempre está presente en el lienzo.
2. **Agregar nodos de comando:** Presiona **Espacio** y agrega comandos (ej. `-addFolder`, `-align`, etc.).
3. **Enlazar ruta de ejecución:** Conecta secuencialmente los sockets de ejecución (con forma de flecha) comenzando desde la salida del nodo `> START`.
4. **Configurar parámetros:** Agrega nodos de parámetros (String, Integer, Float, File/Dir Path) mediante el menú de búsqueda y conecta su salida a las entradas de los nodos de comando.
5. **Ejecutar:** Haz clic en el botón **> Launch** en el nodo `> START` para ejecutar la cadena en RealityCapture.


## Estructura del proyecto

- `nodeRC.py` - Punto de entrada principal.
- `canvas.py` - Lógica de la ventana principal del editor.
- `scene.py` - Escena del lienzo y gestión de eventos de elementos visuales.
- `view.py` - Lógica de vista gráfica, desplazamiento y zoom.
- `nodes_base.py` - Clases base para nodos, sockets y conexiones.
- `nodes_concrete.py` - Implementaciones concretas de nodos especializados (nodos Start, Command, Parameter).
- `configuration.py` - Fuente única de verdad para estilos, configuraciones de interfaz y atajos de teclado.
- `search_menu.py` - Diálogo de búsqueda con autocompletado para crear nodos.
- `diagnostics.py` - Manejador de excepciones y registro de errores.
- `rc_documentation_extractor.py` - Generador de base de datos de comandos a partir de la documentación local de RealityCapture.

## Licencia

Este proyecto se distribuye "tal cual". Consulta los archivos del proyecto para más información.

## Descargo de responsabilidad

Este proyecto es una herramienta independiente y de código abierto no oficial, y no está afiliado, respaldado, patrocinado ni asociado con Capturing Reality, Epic Games ni ninguna de sus filiales. "RealityCapture" y "RealityScan" son marcas comerciales o marcas comerciales registradas de Epic Games, Inc. o sus filiales.
