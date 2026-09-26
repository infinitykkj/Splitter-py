# Splitter-py

Modulo para dividir qualquer arquivo em partes fixas de 1.9 GiB, gerar manifesto JSON com ranges e permitir merge futuro com concatenacao binaria crua (baixo uso de CPU). Tambem gera o manifesto oficial de PS4 direto de pedacos `.pkg` ja splitados (modo `manifest`), sem precisar dividir nada.

## Como usar

### Split

```bash
python -m file_splitter split "C:\caminho\arquivo.bin"
```

Com hash por parte + hash final:

```bash
python -m file_splitter split "C:\caminho\arquivo.bin" --with-hash
```

### Split com manifesto PS4 (JSON)

```bash
python -m file_splitter split "C:\caminho\game.pkg" --pkg --base-url "http://host.com/download"
```

Gera um manifesto estilo PS4 (`game.pkg.manifest.json`) com `originalFileSize`, `packageDigest`, `numberOfSplitFiles` e `pieces[]` (url, fileOffset, fileSize, hashValue).

### Manifesto PS4 sem dividir (arquivos ja splitados)

Modo para quando os pedacos **ja existem** no disco no padrao `<prefixo>_<indice>.pkg` e so falta gerar o manifesto oficial de PS4 (ex.: antes de subir para uma release do GitHub):


```bash
python -m file_splitter manifest "C:\caminho\pasta" --base-url "http://host.com/download"
```

Comportamento:

- **Nao cria novas partes**, apenas le os `.pkg` existentes e grava o manifesto.
- **Um manifesto por grupo de prefixo** (`<prefixo>.manifest.json`), varios manifestos de uma vez.
- Dentro de cada grupo os arquivos sao ordenados pelo indice numerico (`_0`, `_1`, ..., `_10`), e os `fileOffset` sao acumulados (concatenacao binaria em ordem).
- `hashValue` = SHA-1 maiusculo de cada arquivo (streaming).
- `packageDigest` = digest do header do **primeiro** `.pkg` do grupo (mesmo extrator usado no modo `split --pkg`).
- `url` de cada piece = `--base-url` + `/` + nome do arquivo (mesma regra do split PS4).

Opcoes:

| Opcao | Obrigatorio | Descricao |
|---|---|---|
| `dir` | nao | Diretorio com os `.pkg` (default: diretorio atual) |
| `--base-url` | **sim** | Link final da release, ex.: `https://github.com/user/repo/releases/download/TAG` |
| `-o`, `--output-dir` | nao | Onde salvar os manifestos (default: o mesmo diretorio de entrada) |
| `--buffer-size` | nao | Buffer de leitura em bytes (default: 8 MiB) |

Avisos/erros:

- Arquivo `.pkg` fora do padrao (ex.: `jogo.pkg`): ignorado com `[WARN]`.
- Indices faltando num grupo (ex.: `_0`, `_1`, `_3`): aviso `[WARN]` com os indices ausentes, o manifesto e gerado mesmo assim.
- Indice duplicado no mesmo grupo (ex.: `jogo_0.pkg` e `jogo-0.pkg`): erro.
- Nenhum `<prefixo>_<indice>.pkg` no diretorio, ou `--base-url` ausente: erro.

Exemplo de manifesto gerado (`<prefixo>.manifest.json`):

```json
{
  "originalFileSize": 6000000000,
  "packageDigest": "96FB67A9FAF6010CFCBF957C2AB83C3D82295C3852591FDB176EC9934E8C5C55",
  "numberOfSplitFiles": 3,
  "pieces": [
    {
      "url": "https://github.com/user/repo/releases/download/TAG/Aragami.2.CUSA23443.PS4_0.pkg",
      "fileOffset": 0,
      "fileSize": 2000000000,
      "hashValue": "0434C5E9E2B2295FE2B8027B70CEF1AF8948E683"
    },
    {
      "url": "https://github.com/user/repo/releases/download/TAG/Aragami.2.CUSA23443.PS4_1.pkg",
      "fileOffset": 2000000000,
      "fileSize": 2000000000,
      "hashValue": "757B445C32FCC1F61F8777218226F8C2A01365DF"
    },
    {
      "url": "https://github.com/user/repo/releases/download/TAG/Aragami.2.CUSA23443.PS4_2.pkg",
      "fileOffset": 4000000000,
      "fileSize": 2000000000,
      "hashValue": "9EA1FEBA35ED19DB7369A289D714D3D28CBA7C1A"
    }
  ]
}
```

O formato e identico ao gerado pelo modo `split --pkg`, entao os dois modos podem ser usados de forma intercambiavel.

### Split com manifesto PS3 (hfs_manifest XML)

```bash
python -m file_splitter split "C:\caminho\game.pkg" --ps3 --base-url "http://host.com/download" --part-size 2000000000
```

Gera um manifesto HFS estilo PS3 (`game.pkg.hfs_manifest.xml`) com `file_name`, `file_size`, `number_of_split_files` e as tags `<pieces file_size="..." index="..." url="..."/>`. As partes sao nomeadas no padrao `game_00.pkg`, `game_01.pkg`, etc. `--base-url` e obrigatorio neste modo.

### Merge

```bash
python -m file_splitter merge "C:\caminho\arquivo.bin.manifest.json" "C:\caminho\arquivo_restaurado.bin"
```

Com validacao de hash (se manifesto tiver hash):

```bash
python -m file_splitter merge "C:\caminho\arquivo.bin.manifest.json" "C:\caminho\arquivo_restaurado.bin" --verify-hash
```

### Validar manifesto e presenca das partes

```bash
python -m file_splitter validate "C:\caminho\arquivo.bin.manifest.json"
```

## Manifesto JSON Final

/<file-dir/<filename>.manifest.json
- `file_name`: nome do arquivo original
- `file_size`: tamanho total em bytes
- `chunk_size`: tamanho alvo de cada parte
- `parts[]`: lista ordenada das partes com:
  - `part`: indice sequencial
  - `file`: nome do arquivo da parte
  - `start`: byte inicial (inclusive)
  - `end`: byte final (inclusive)
  - `size`: tamanho da parte em bytes
  - `sha256` (opcional)

## Manifesto PS4 (formato oficial)

Gerado pelos modos `split --pkg` e `manifest` (`<arquivo>.manifest.json` ou `<prefixo>.manifest.json`):

- `originalFileSize`: tamanho total do arquivo original em bytes (soma das pieces)
- `packageDigest`: digest SHA-256 do header do PKG (hex maiusculo)
- `numberOfSplitFiles`: quantidade de pieces
- `pieces[]`: lista ordenada das partes com:
  - `url`: `--base-url` + `/` + nome do arquivo da parte
  - `fileOffset`: byte inicial (acumulado, comeca em 0)
  - `fileSize`: tamanho da parte em bytes
  - `hashValue`: SHA-1 da parte (hex maiusculo)


## notas de performance

- I/O em streaming com `buffer` (default 8 MiB)
- copia binaria direta (sem compressao/descompressao)
- merge por concatenacao em ordem do manifesto
- ranges inclusivos para reconstruir sem calculos complexos

Esse desenho permite merge com custo de CPU muito baixo, com foco no throughput de disco.
