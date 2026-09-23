# Device map v2 – obserwable i solver

Część A: co zbiera device map. Część B (na końcu): algorytm przydziału i spójność między grami.

# Część A – device map

Zasada nadrzędna: **device map przechowuje fakty i tiery, a nie wyniki.** Scoring i wagi żyją w solverze, więc da się je stroić bez przerabiania map.

## 1. Kontrolka

| Pole | Wartości | Po co |
|---|---|---|
| `device` | VID/PID, nazwa | identyfikacja urządzenia |
| `raw_ids` | przyciski / oś / hat | surowe wejścia dla adapterów gier |
| `kind` | `momentary`, `toggle`, `encoder`, `hat4`, `hat8`, `ministick`, `trigger2stage`, `axis` | typ fizyczny |
| `states` | lista pozycji: `latching: bool`, `emits_signal: bool` | toggle 2/3-poz., pozycje sprężynujące (np. ON-OFF-(ON)), „cichy” środek do zasymulowania przy eksporcie |
| `axis.centered` | bool | sprężyna vs tarcie |
| `axis.detents` | lista pozycji | detenty (afterburner, idle) |
| `axis.range` / `axis.noise` | liczby | precyzja osi |
| `access` | lista `(pozycja, palec)` | skąd i czym się obsługuje |
| `blind_distinct` | `none` / `low` / `high` | rozróżnialność na ślepo (kształt, faktura, izolacja) |
| `accident_risk` | `low` / `med` / `high` | osłony, klapki, bliskość triggera |
| `hold_ok` | bool | wygoda długiego trzymania |
| `rapid_ok` | bool | wygoda szybkiego wielokrotnego klikania |
| `direction` | `up`, `down`, `fwd`, `aft`, `left`, `right`, `cw`, `ccw` | pary akcji (zoom in/out, range up/down) na przeciwne kierunki |
| `cluster` | ID grupy | hat, rząd przycisków → grupy semantyczne akcji |
| `modifier_ok` | bool | kandydat na shift/modyfikator |
| `role_tag` | np. `TMS`, `DMS`, `CMS` (opcjonalne) | prior dla replik; jeśli jest, wygrywa z heurystyką |

## 2. Słowniki

| Słownik | Wartości |
|---|---|
| Palce | `thumb`, `index`, `middle`, `ring`, `pinky` |
| Części | `stick`, `stick_base`, `throttle`, `throttle_base`, `panel`, … |
| Poziomy pozycji | `HOME` (0), `EXTENDED` (1), `BASE` (2), `OFF` (3) |

Pozycja = para `(część, poziom)`, np. `(throttle, HOME)`, `(stick_base, BASE)`.

- **HOME**: dłoń w normalnym chwycie, palce na swoich miejscach
- **EXTENDED**: dłoń w chwycie, palec się wyciąga albo lekko przesuwa
- **BASE**: dłoń schodzi z chwytu na bazę/panel urządzenia
- **OFF**: dłoń opuszcza urządzenie (klawiatura, osobny panel)

## 3. Część urządzenia

| Pole | Wartości | Po co |
|---|---|---|
| `hand` | `L` / `R` | przypisanie ręki |
| `leaving_home_releases_flight` | bool | zejście z HOME puszcza sterowanie lotem, więc tylko akcje naziemne/startup |

## 4. Reguły wyprowadzane (nie zapisywane)

- **Tier sięgnięcia** = minimum poziomu pozycji z `access`.
- **Kompatybilność jednoczesnego użycia**: dwie kontrolki są kompatybilne, jeśli są na różnych rękach **albo** istnieje pozycja, z której obie są osiągalne **różnymi palcami**.
- **Override**: ręczna lista wyjątków (np. kciuk wciska dwa sąsiednie przyciski naraz, mały palec nie sięga pinky levera przy wychylonym drążku).

## 5. Wizard i UX

- Detekcja „wciśnij kontrolkę” → automatycznie `raw_ids`, `kind`, `states`.
- Domyślne wartości per `kind`; ręcznie zostaje głównie ergonomia.
- Szablony dla popularnych urządzeń (Warthog, Virpil, VKB, WinWing) z gotowymi `access` i częściami.
- Pytania o kompatybilność tylko dla par **kandydaci na modyfikator × kontrolki tej samej ręki** (wygodne / niewygodne).

# Część B – solver

## 6. Wybór algorytmu

| | Algorytm węgierski | CP-SAT (Google OR-Tools) |
|---|---|---|
| Co robi | przydział 1:1 akcja → slot, minimum sumy kosztów | solver ograniczeń na zmiennych bool „akcja A na slocie S” |
| Szybkość | O(n³), milisekundy | sekundy przy dziesiątkach tysięcy zmiennych; limit czasu + najlepsze znalezione rozwiązanie |
| Ograniczenia między przypisaniami | **nie** (widzi tylko koszt pojedynczego dopasowania) | **tak** (pary kierunków, klastry, spójność między grami) |
| Rola | szybki podgląd, punkt startowy (hint) dla CP-SAT | główny silnik |

Bindingi CP-SAT: Python, C++, C#, Java. Wynik węgierskiego można podać CP-SAT-owi jako hint, co przyspiesza start.

## 7. Model

- **Slot = krotka `(kontrolka, stan, warstwa modyfikatora, kontekst)`**, a nie sama kontrolka. Toggle 3-pozycyjny, shift i konteksty (Elite: statek/SRV/na piechotę, X4: lot/na piechotę/menu) to po prostu więcej slotów, bez specjalnych przypadków.
- **Zmienna**: `x[akcja, slot] ∈ {0,1}`.
- **Opcja „niezbindowana”** dla każdej akcji, z karą zależną od jej ważności. Akcji jest zawsze więcej niż slotów, więc bez tego solver zwróci „brak rozwiązania” zamiast rozsądnego kompromisu.

### Ograniczenia twarde
- typ sygnału akcji pasuje do `kind`/`states` slotu (oś → oś, akcja stanowa → toggle albo zasymulowany stan)
- max jedna akcja na slot w obrębie kontekstu (konflikt liczy się tylko wewnątrz kontekstu)
- każda akcja przypisana dokładnie raz (albo do opcji „niezbindowana”)
- akcje używane w locie nie trafiają na części z `leaving_home_releases_flight` poza HOME
- przypięcia `lock` z profili (sekcja 8)

### Kary miękkie (funkcja celu)
- ergonomia: tier sięgnięcia × częstotliwość/presja czasu akcji, `blind_distinct`, `accident_risk` dla akcji krytycznych
- pary akcji (in/out, up/down) nie na przeciwnych `direction` tego samego `cluster`
- rozbicie grupy semantycznej na wiele klastrów
- odchylenie od „domu roli” (sekcja 8)
- zmiana względem poprzedniego rozwiązania (sekcja 9)
- niezbindowanie akcji (waga wg ważności)

## 8. Spójność między grami – zwężające profile

### Kanoniczne role
Taksonomia ról ponad grami (np. `gear_toggle`, `weapon_release`, `target_designate`). Adaptery gier mapują swoje akcje na role. **Spójność liczymy na rolach, nie na nazwach akcji z gier.**

### Kaskada profili
`user global → gatunek (mil-sim / space) → gra → samolot/statek`

Niższy poziom nadpisuje wyższy. Gra, w której rola nie istnieje (np. podwozie w SRV w Elite), po prostu jej nie dziedziczy.

Siła przypięcia roli na danym poziomie:

| Siła | Znaczenie w solverze |
|---|---|
| `lock` | ograniczenie twarde: rola na tym slocie |
| `strong` | preferencja, duża waga kary za odchylenie |
| `weak` | preferencja, mała waga |
| `free` | solver decyduje |

### Dom roli
Dla każdej roli jedna wspólna zmienna „dom” (wybór slotu na poziomie profilu). Przypisanie w każdej grze dostaje karę za odchylenie, **stopniowaną**:

| Odchylenie od domu roli | Kara |
|---|---|
| ten sam slot | 0 |
| ta sama kontrolka, inna warstwa/stan | mała |
| ten sam klaster | średnia |
| ta sama ręka | duża |
| gdziekolwiek indziej | bardzo duża |

Kara mnożona przez siłę przypięcia (`strong` / `weak`). Efekt: przy braku miejsca rola „ucieka” na sąsiedni przycisk, a nie na drugą rękę.

### Tryby rozwiązywania
- **Wspólny**: wszystkie gry w jednym modelu, domy ról wybiera solver. Najlepsza globalna spójność, większy model.
- **Sekwencyjny**: najpierw gra-kotwica (np. BMS, kanoniczny hotas F-16), jej wynik staje się preferencjami (`strong` / `weak`) dla kolejnych gier. Tańszy i bardziej przewidywalny.

## 9. Stabilność w czasie

Przy dodaniu gry/modułu albo zmianie device mapy: kara za każde przypisanie różne od poprzedniego rozwiązania (poprzednie rozwiązanie podane też jako hint). Bez tego jeden nowy samolot w DCS przetasuje pamięć mięśniową we wszystkich grach.
