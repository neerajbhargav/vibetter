# Shop fixture

A small synthetic bookshop used by the VIBETTER tests. It is never run.
The Python package prices a cart; the web folder shows it with Vue.

- `shop/cart.py` holds the cart and applies discount codes.
- `shop/pricing.py` computes tax and looks up discount codes.
- `web/src/lib/format.ts` formats prices for display.
