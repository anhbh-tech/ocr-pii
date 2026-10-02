# Fixtures: invented, every one

Every name, number, address and e-mail in this directory was made up for the
tests. None comes from a client document, a public register or pii-lab's
corpus. Invented values follow shapes that cannot collide with real ones:

- people and places use placeholder words (Mẫu, Thử, Hư Cấu, Giả Định, Ví Dụ);
- e-mail domains are `example.test` (RFC 2606 reserves `.test`);
- phones are `0900 000 xxx` / `+84 900 000 xxx`;
- ID numbers are `00109900000x`; tax codes `031234567x`;
- hotlines are the reserved ranges with a reserved subscriber number:
  `1-800-555-01xx` / `(833) 555-01xx` (NANP 555-01xx is reserved for fiction)
  and `1900 0000` / `1800 0000`;
- account numbers are `99000000000001`, routing numbers `990000001`, card
  numbers `9900 0000 0000 0001`, transaction ids `99000000000000000001` —
  every one a 9 followed by 9s and a small serial, a shape no issuer uses;
- the e-seal fixture's IP is `10.900.900.900`, which is not an address;
- case-variable fixtures (`tests/test_casevars.py`) use the same placeholder
  words and the matter codes `hc1023.test` / `hc1024.test`;
- the roster's "public parties" are invented too — the real roster is
  supplied at run time and never committed.

Each fixture that carries a person name says so where a reader lands first:
`case_synthetic.txt` opens with a `SYNTHETIC TEST DATA` line,
`synthetic_register.json` with a `_synthetic` key, and every roster entry's
`why` starts with `SYNTHETIC TEST DATA`.

`tests/test_synthetic_only.py` fails if a tracked file carries an e-mail,
phone or 12-digit ID outside these shapes.
