# NodeRC

![Screenshot](images/Screenshot.png)

[English](../README.md) | [Українська](README.uk.md) | [Español](README.es.md) | [中文](README.zh.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [日本語](README.ja.md) | [हिन्दी](README.hi.md) | [Português](README.pt.md) | [العربية](README.ar.md)

O NodeRC é um editor e interface visual baseado em nós não oficial para comandos CLI do RealityCapture / RealityScan. Escrito em Python usando PyQt5, o projeto permite conectar e gerenciar visualmente nós de comando em uma tela (canvas) interativa, fornecendo uma interface amigável para a automatização de fluxos de trabalho.

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

### Controles e Atalhos

- **Arrastar Tela (Pan):** Clique e segure o **botão central do mouse (MMB)** e arraste.
- **Zoom:** Role a **roda do mouse**.
- **Adicionar Nó:** Pressione **Espaço** ou clique com o **botão direito** em um espaço vazio da tela para abrir o Menu de Pesquisa. Selecione um nó de comando ou parâmetro para criá-lo na posição do cursor.
- **Conectar Sockets:** Arraste uma linha de um socket de saída para um socket de entrada compatível.
  - Arrastar de um socket e soltar em uma área vazia da tela abre o Menu de Pesquisa para selecionar e autoconectar um novo nó.
- **Excluir Nó/Conexão:** Selecione o item e pressione a tecla **Delete**.
- **Agrupar Nós:** Selecione os nós e pressione **Ctrl + G** para emoldurá-los.
- **Duplicar Nós:** Selecione os nós e pressione **Ctrl + D**.
- **Copiar / Colar:** Selecione os nós e pressione **Ctrl + C** para copiar, e **Ctrl + V** para colar na posição do cursor.
- **Desfazer / Refazer:** Pressione **Ctrl + Z** para desfazer e **Ctrl + Y** (ou **Ctrl + Shift + Z**) para refazer.
- **Selecionar Tudo:** Pressione **Ctrl + A**.
- **Alternar Grade (Grid):** Pressione a tecla **G** para mostrar/ocultar a grade.
- **Ajustar Visualização:** Pressione a tecla **F** para focar a visualização nos nós selecionados (ou em todos se nenhum estiver selecionado).
- **Renomear Nó:** Selecione um nó de parâmetro e pressione **F2**.
- **Tela Cheia:** Pressione **F11** para alternar o modo de tela cheia.

### Fluxo de Execução

1. **Iniciar a Cadeia:** O nó `> START` está sempre presente na tela.
2. **Adicionar Nós de Comando:** Pressione **Espaço** e adicione comandos (ex: `-addFolder`, `-align`, etc.).
3. **Vincular Execução:** Conecte os sockets de execução (em formato de seta) sequencialmente, começando pela saída do nó `> START`.
4. **Configurar Parâmetros:** Adicione nós de parâmetros (String, Integer, Float, File/Dir Path) via Menu de Pesquisa e conecte sua saída aos sockets de entrada dos nós de comando.
5. **Executar:** Clique no botão **> Launch** no nó `> START` para executar a cadeia no RealityCapture.


## Estrutura do Projeto

- `nodeRC.py` - Ponto de entrada principal.
- `canvas.py` - Lógica da janela principal do editor.
- `scene.py` - Cena da tela (canvas) e tratamento de eventos de itens visuais.
- `view.py` - Lógica da visualização gráfica, deslocamento (panning) e zoom.
- `nodes_base.py` - Classes base para nós, sockets e conexões.
- `nodes_concrete.py` - Implementações concretas de nós especializados (nós Start, Command, Parameter).
- `configuration.py` - Fonte única de verdade para estilos, configurações de UI e atalhos.
- `search_menu.py` - Caixa de diálogo de pesquisa com autocompletar para criar nós.
- `diagnostics.py` - Tratamento de exceções e registro de erros.
- `rc_documentation_extractor.py` - Utilitário para construir o banco de dados de comandos a partir da documentação local do RealityCapture.

## Licença

Este projeto é distribuído "como está". Consulte os arquivos do projeto para obter mais informações.

## Isenção de Responsabilidade

Este projeto é uma ferramenta de código aberto independente e não oficial, e não é afiliado, endossado, patrocinado ou associado à Capturing Reality, Epic Games ou a qualquer uma de suas subsidiárias. "RealityCapture" e "RealityScan" são marcas comerciais ou registradas da Epic Games, Inc. ou de suas subsidiárias.
