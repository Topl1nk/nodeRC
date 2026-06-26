# NodeRC

![Screenshot](images/screenshot.png)

[English](README.md) | [Русский](README.ru.md) | [Español](README.es.md) | [中文](README.zh.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [日本語](README.ja.md) | [हिन्दी](README.hi.md) | [Português](README.pt.md) | [العربية](README.ar.md)

O NodeRC é um editor visual baseado em nós escrito em Python usando PyQt5. O projeto permite criar, conectar e gerenciar nós em uma tela (canvas) interativa, fornecendo uma interface amigável para programação visual ou construção de gráficos lógicos.

## Funcionalidades
- **Canvas Interativo:** Um espaço de trabalho infinito com suporte a deslocamento e zoom.
- **Arquitetura de Nós:** Vários tipos de nós com suporte a conexões de entrada e saída (sockets).
- **Conexões Dinâmicas:** Vinculação visual de portas de execução e portas de dados.
- **Sistema de Configuração:** Cores, tamanhos e estilos personalizáveis através de um arquivo de configuração centralizado.
- **Menu de Pesquisa:** Um menu conveniente para adicionar novos nós rapidamente ao canvas.

## Requisitos
- Python 3.7+
- PyQt5

## Instalação

1. Clone o repositório:
   ```bash
   git clone <URL_do_repositorio>
   cd nodeRC
   ```

2. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```

## Uso
Para iniciar o editor, execute:
```bash
python nodeRC.py
```

## Estrutura do Projeto
- `nodeRC.py` - Ponto de entrada principal.
- `canvas.py` - Lógica do canvas interativo e gerenciamento de gráficos.
- `nodes.py` - Classes base e especializadas para nós e sockets.
- `configuration.py` - Arquivo de configuração (cores, estilos, parâmetros de UI).
- `search_menu.py` - Caixa de diálogo para pesquisar e adicionar nós.
- `diagnostics.py` - Registro (logging) e tratamento de exceções.
- `rc_documentation_extractor.py` - Utilitário para extrair documentação de comandos.

## Licença
Este projeto é distribuído "como está". Consulte os arquivos do projeto para obter mais informações.
