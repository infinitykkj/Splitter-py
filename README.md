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

### Sem hash (campos vazios, nenhum calculo)

```bash
python -m file_splitter split "C:\caminho\game.pkg" --pkg --base-url "http://host.com/download" --no-hash
python -m file_splitter manifest "C:\caminho\pasta" --base-url "http://host.com/download" --no-hash
```

`--no-hash` desliga todos os hashes: `packageDigest` e cada `hashValue` sao gravados como `""` (e no manifesto generico os campos `sha256`/`sha1` ficam ausentes). Nada e lido para calcular digest. Mutuamente exclusivo com `--with-hash`.

### Manifesto PS4 sem dividir (arquivos ja splitados)

Modo para quando os pedacos **ja existem** no disco no padrao `<prefixo>_<indice>.pkg`


```bash
python -m file_splitter manifest "C:\caminho\pasta" --base-url "http://host.com/download"
```

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
