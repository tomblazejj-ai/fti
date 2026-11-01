# FTI v mobilu

Aplikace je napsaná tak, že v telefonu funguje jako normální aplikace (ikona na ploše,
celá obrazovka, poslední data i bez signálu). Aby běžela i když je PC vypnuté, musí
být na internetu. Nejjednodušší cesta zdarma je GitHub:

- **GitHub Actions** každých 30 minut stáhne data (stejné zdroje jako aplikace na PC)
  a připraví aktuální snímek,
- **GitHub Pages** ho zveřejní na adrese https://tomblazejj-ai.github.io/fti/,
- telefon si živé ceny zlata, EUR/USD a GBP/USD bere přímo z Krakenu.

Co je potřeba jednou udělat (uživatel):

1. Založit si zdarma účet na github.com (účet je tvůj, e-mail zadáváš jen ty).
2. Vytvořit veřejný repozitář (např. `fti`). Veřejný proto, že Pages i Actions jsou
   zdarma jen pro veřejné repozitáře — kdo zná adresu, uvidí přehled trhů (žádné
   osobní údaje v něm nejsou).
3. Nahrát do něj tenhle projekt a v nastavení repozitáře zapnout
   *Settings → Pages → Source: GitHub Actions*.
4. V telefonu otevřít adresu stránky a dát *Přidat na plochu* (Android: menu ⋮,
   iPhone: tlačítko Sdílet).

Technicky: `.github/workflows/mobil.yml`, snímek `backend/app/export_static.py`,
build webu s `VITE_STATIC=1`.

Nová verze se v telefonu ukáže při dalším otevření aplikace (stránka se bere
nejdřív ze sítě). Když je telefon bez signálu, ukážou se poslední stažená data.
