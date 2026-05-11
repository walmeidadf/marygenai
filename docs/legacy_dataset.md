# Legacy Dataset Notes

Legacy files are stored locally in `temp/legacy/` and ignored by Git.

## Files

- `colunas-ontologia.xlsx`
- `cannadocs/Estudos-Grid view.csv`
- `cannadocs/Canabinoides-Grid view.csv`
- `cannadocs/Condicoes Medicas-Grid view.csv`
- `cannadocs/Sistemas do Organismo-Grid view.csv`
- `cannadocs/Terpenos-Grid view.csv`
- `cannadocs/Glossario-Grid view.csv`
- `cannadocs/Calculadora-Grid view.csv`

Some filenames contain accents because they came from the legacy export.

## Observations From Initial Profiling

The studies table has 7,347 rows, 7,347 unique URLs, and 7,347 unique study IDs. Study ID `6245` is missing from the numeric sequence. There are 17 duplicate English titles and 12 duplicate Portuguese titles.

The dataset is strongly PubMed/NLM-oriented:

- `nlm.nih.gov`: 5,491 studies;
- `www.sciencedirect.com`: 379;
- `onlinelibrary.wiley.com`: 179;
- `www.mdpi.com`: 129;
- `www.frontiersin.org`: 103.

Top legacy study types:

- `Metanalise`: 3,176;
- `Estudo Animal`: 1,634;
- `Estudo Laboratorial`: 971;
- `Ensaio Clinico`: 751;
- `Ensaio Clinico Duplo-Cego`: 575;
- `Metanalise Clinica`: 240.

Top medical conditions by split count:

- pain;
- cancer;
- inflammation;
- cannabis adverse effects;
- dependence;
- anxiety;
- cannabis dependence;
- chronic pain;
- cardiovascular disease;
- depression;
- epilepsy.

Sparse fields:

- dosage: about 12%;
- treatment duration: about 3%;
- adverse events: about 2%;
- starting dose and maximum dose: about 1%.

These sparse fields should not be treated as reliable default metadata from abstract-only extraction.
