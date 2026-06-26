# NodeRC

[English](README.md) | [Русский](README.ru.md) | [Español](README.es.md) | [中文](README.zh.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [日本語](README.ja.md) | [हिन्दी](README.hi.md) | [Português](README.pt.md) | [العربية](README.ar.md)

NodeRC es un editor visual basado en nodos escrito en Python utilizando PyQt5. El proyecto te permite crear, conectar y gestionar nodos en un lienzo interactivo, proporcionando una interfaz cómoda para la programación visual o la construcción de gráficos lógicos.

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

## Estructura del proyecto
- `nodeRC.py` - Punto de entrada principal.
- `canvas.py` - Lógica del lienzo interactivo y gestión de gráficos.
- `nodes.py` - Clases base y especializadas para nodos y sockets.
- `configuration.py` - Archivo de configuración (colores, estilos, parámetros de interfaz).
- `search_menu.py` - Diálogo para buscar y agregar nodos.
- `diagnostics.py` - Registro y manejo de excepciones.
- `rc_documentation_extractor.py` - Utilidad para extraer documentación de comandos.

## Licencia
Este proyecto se distribuye "tal cual". Consulta los archivos del proyecto para más información.
