# AI Execution Guide — Cara Membaca Instruksi User

> Dokumen ini mendokumentasikan pola komunikasi user dan bagaimana AI harus
> merespon setiap jenis instruksi. Berlaku untuk SEMUA project user.
>
> **Bacalah dokumen ini BEFORE mengerjakan task apapun untuk user ini.**

## Tools Available

| Tool | Path / Command |
|------|---------------|
| **Flutter SDK** | `C:\Android\flutter` (Dart 3.7.2) |
| **Dart** | `& "C:\Android\flutter\bin\cache\dart-sdk\bin\dart.exe"` |
| **Flutter** | `& "C:\Android\flutter\bin\cache\dart-sdk\bin\dart.exe" "C:\Android\flutter\bin\cache\flutter_tools.snapshot"` |
| **JDK** | `C:\Program Files\Android\Android Studio\jbr` (JDK 21) |
| **Android SDK** | `C:\Users\rafki\AppData\Local\Android\Sdk` |
| **ADB** | `& "C:\Users\rafki\AppData\Local\Android\Sdk\platform-tools\adb.exe"` |
| **Emulator** | `& "C:\Users\rafki\AppData\Local\Android\Sdk\emulator\emulator.exe" -avd Pixel_4` |
| **Project** | `D:\zayn\project\comic_downloader` (root), `build_temp\` (build copy) |
| **Shell** | PowerShell 7+ (`pwsh`) |
| **Tools AI** | Read, Edit, Write, Bash, Glob, Grep, WebSearch, WebFetch, Question, Task, TodoWrite, Skill |

## Java Home Wajib
```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
$env:ANDROID_HOME = "C:\Users\rafki\AppData\Local\Android\Sdk"
```

## Flutter Run (tanpa .bat wrapper)
```powershell
& "C:\Android\flutter\bin\cache\dart-sdk\bin\dart.exe" "C:\Android\flutter\bin\cache\flutter_tools.snapshot" run -d emulator-5554
```

## Flutter Analyze
```powershell
& "C:\Android\flutter\bin\cache\dart-sdk\bin\dart.exe" "C:\Android\flutter\bin\cache\flutter_tools.snapshot" analyze
```

---

## 1. Nada & Gaya Komunikasi User

| Ciri | Contoh | Respon AI |
|------|--------|-----------|
| **Imperatif langsung** | "lakukan", "buat", "cari", "push", "selesaikan" | Eksekusi segera tanpa tanya-konfirmasi |
| **Campur bahasa** | Indonesia + Inggris campur | Pahami maksud dari konteks, bahasa tidak perlu sempurna |
| **Singkat & padat** | 1-2 kalimat perintah | Jangan minta elaborasi — langsung kerjakan |
| **Feedback kegagalan langsung** | "masih error", "masih tidak", "error still here" | Fix sebelumnya GAGAL — cari pendekatan baru, jangan ulangi hal yang sama |
| **Tidak suka analisis panjang** | Tidak minta penjelasan detail | Jawab 2-3 kalimat, langsung ke inti: akar masalah + solusi |
| **Konfirmasi sebelum lanjut** | Kadang bertanya "kan?" di akhir | Jawab dulu pertanyaannya, baru tindak lanjut |

---

## 2. Sistem Prioritas Instruksi

### P1 — Push ke Remote (Tertinggi)
Perintah: `"push"`, `"push dulu"`, `"push ke main"`

**Reaksi WAJIB:**
```
git add -A
git commit -m "Scope: description"
git push origin <branch>
```
- Jangan tunda, jangan tanya, jangan tambah perubahan lain
- Push dulu, baru lanjut kerja berikutnya
- Commit message bahasa Inggris, format: `"Scope: description"`

### P2 — Fix Bug / Error
Perintah: `"masih error"`, `"cari masalahnya"`, `"selesaikan"`

**Reaksi:**
1. Cari reference working version (branch backup, git diff, atau commit lama)
2. Bandingkan dengan versi yang bermasalah — cari apa yang BERBEDA
3. Trace flow lengkap — jangan tebak
4. Cari chain reaction: satu gejala bisa dari 2-3 bug berantai
5. Fix root cause + tambah safety net untuk cegah terulang
6. Verifikasi: `analyze/lint`, build, test
7. Update dokumentasi terkait
8. Tunggu instruksi push

### P3 — Dokumentasi
Perintah: `"buat md"`, `"tulis di doc"`, `"update todo"`

**Reaksi:**
- Update/create dokumentasi yang relevan
- Dokumentasikan root cause bug agar tidak terulang
- Simpan di folder project

### P4 — Build / Release
Perintah: `"build"`, `"buat release"`, `"app release"`

**Reaksi:**
- Jalankan build command sesuai project (release/debug)
- Laporkan path file output + ukuran

---

## 3. Pola Investigasi Bug

Saat user lapor error, urutannya:

### Langkah 1 — Cari Reference Working
```bash
git diff <working-branch>..<current-branch> -- <file>
```
Asumsikan versi yang WORKING sebagai acuan.

### Langkah 2 — Trace Flow
Baca kode dari trigger sampai output. Perhatikan:
- State management flow
- Database query / constraint
- async timing / race condition
- Null safety

### Langkah 3 — Cari Chain Reaction
Satu bug yang user lihat sering disebabkan oleh beberapa bug berantai:
- Bug A (root cause) → Bug B (tersembunyi) → Bug C (yang terlihat)
- Fix semuanya, bukan hanya gejala

### Langkah 4 — Safety Net
Setelah fix root cause, tambah pengaman (cleanup, validasi) agar bug serupa tidak muncul lagi.

---

## 4. Aturan Coding

### WAJIB dilakukan
- ✅ `analyze` / `lint` setelah selesai coding — pastikan **0 errors**
- ✅ `const` constructor sebisa mungkin
- ✅ Named parameters untuk function/widget
- ✅ Private fields/methods pakai `_` prefix
- ✅ Ikuti pattern/konvensi file yang sudah ada
- ✅ Backup/reference branch jangan di-touch — hanya untuk referensi

### JANGAN dilakukan
- ❌ Jangan tambah komentar (kecuali TODO/FIXME penting)
- ❌ Jangan buat file baru kalau masih bisa edit existing
- ❌ Jangan tambah dependency/pustaka baru tanpa izin
- ❌ Jangan ubah konfigurasi project (analysis_options, tsconfig, dll) tanpa alasan jelas
- ❌ Jangan tebak/tulis kode tanpa verifikasi

---

## 5. Pola Respons yang Tepat

| Situasi | Respons SALAH | Respons BENAR |
|---------|--------------|---------------|
| User bilang "error masih" | "Saya sudah coba A, B, C..." (defensif) | Langsung cari root cause baru, bandingkan dengan versi working |
| User bilang "push dulu" | "Sebentar saya tambah fix lain" (menunda) | Push segera, tanpa tambahan |
| User tanya konfirmasi | "Apakah Anda ingin saya lanjutkan?" | Jawab dulu pertanyaannya, baru tindak lanjut |
| User minta penjelasan | Paragraf panjang analisis | 2-3 kalimat: akar masalah + apa yang dilakukan |

---

## 6. Alur Kerja Standar

```
User memberi instruksi
  ↓
Apakah P1 (push)?  → PUSH SEKARANG, selesai
  ↓
Apakah P2 (fix)?   
  → Cari reference working
  → Trace flow lengkap
  → Cari chain reaction
  → Fix + safety net
  → Verify (analyze, build, test)
  → Update docs
  → Tunggu instruksi push
  ↓
Apakah P3 (docs)?  → Update dokumentasi
  ↓
Apakah P4 (build)? → Build + lapor hasil
```

---

## 7. Catatan Penting

- **Bahasa UI/teks** mengikuti preferensi user (bisa Indonesia, Inggris, atau campuran)
- **Commit message** selalu bahasa Inggris dengan format `"Scope: description"`
- **Branch utama** adalah branch deployment — jangan commit langsung tanpa verify
- **Branch backup/reference** jangan di-touch, hanya untuk perbandingan
- Dokumentasi bug dan fix itu WAJIB — agar tidak terulang di masa depan
