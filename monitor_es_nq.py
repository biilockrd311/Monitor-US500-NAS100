import datetime
import io
import os
import sys
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
import pytz
import requests
import yfinance as yf

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
REPORTE_MANUAL = os.environ.get("REPORTE_MANUAL", "").strip()
TZ_NY = pytz.timezone("America/New_York")

ACTIVOS = {"ES (E-mini S&P 500)": "ES=F", "NQ (E-mini Nasdaq 100)": "NQ=F"}


def fmt(val):
  return f"{val:.2f}" if pd.notna(val) else "—"


def analizar_pa(s_open, s_high, s_low, s_close, ref_high, ref_low, ref_name):
  rng = s_high - s_low
  body = abs(s_close - s_open)
  body_pct = (body / rng * 100.0) if rng > 0 else 0.0
  close_pos = ((s_close - s_low) / rng * 100.0) if rng > 0 else 50.0

  if body_pct > 65.0:
    estructura = (
        "Tendencial Alcista (Impulso Fuerte)"
        if s_close > s_open
        else "Tendencial Bajista (Impulso Fuerte)"
    )
  elif body_pct >= 30.0:
    estructura = (
        "Sesgo Alcista Moderado"
        if s_close > s_open
        else "Sesgo Bajista Moderado"
    )
  else:
    estructura = "Consolidación / Rango en Equilibrio"

  extremos = f"Dentro del rango de {ref_name} (Compresión)"
  if pd.notna(ref_high) and pd.notna(ref_low):
    if s_high > ref_high and s_close < ref_high:
      extremos = f"Falso Quiebre Alcista (Trampa / Rechazo en Máx {ref_name})"
    elif s_high > ref_high and s_close >= ref_high:
      extremos = f"Ruptura y Aceptación Alcista (Sobre Máx {ref_name})"
    elif s_low < ref_low and s_close > ref_low:
      extremos = f"Falso Quiebre Bajista (Spring / Rechazo en Mín {ref_name})"
    elif s_low < ref_low and s_close <= ref_low:
      extremos = f"Ruptura y Aceptación Bajista (Bajo Mín {ref_name})"

  return estructura, extremos, rng, close_pos


def evaluar_ib(ib_high, ib_low, sub_high, sub_low, sub_close):
  if pd.isna(ib_high) or pd.isna(ib_low):
    return "No disponible"
  if sub_high > ib_high and sub_low < ib_low:
    return "Día Neutral / Expansión Ambos Lados (Rompió IBH e IBL)"
  elif sub_high > ib_high and sub_close >= ib_high:
    return "Día Tendencial Alcista (Aceptación sobre IBH)"
  elif sub_high > ib_high and sub_close < ib_high:
    return "Ruptura Fallida de IBH (Rechazo hacia el Balance Inicial)"
  elif sub_low < ib_low and sub_close <= ib_low:
    return "Día Tendencial Bajista (Aceptación bajo IBL)"
  elif sub_low < ib_low and sub_close > ib_low:
    return "Ruptura Fallida de IBL (Rechazo hacia el Balance Inicial)"
  return "Día Rotacional en Rango (Dentro del Balance Inicial)"


def generar_imagen_15m(
    df_15m,
    nombre_activo,
    titulo,
    sub_start,
    sub_end,
    pdh,
    pdl,
    ib_high,
    ib_low,
    t_as,
    t_lnd,
    t_ny,
):
  """Genera un gráfico de velas de 15m estilo TradingView Dark con los niveles y movimientos."""
  mc = mpf.make_marketcolors(
      up="#26a69a",
      down="#ef5350",
      edge="inherit",
      wick="inherit",
      volume="in",
  )
  estilo = mpf.make_mpf_style(
      base_mpf_style="nightclouds",
      marketcolors=mc,
      facecolor="#131722",
      edgecolor="#2a2e39",
      figcolor="#131722",
      gridcolor="#1e222d",
      gridstyle="--",
  )

  fig, axlist = mpf.plot(
      df_15m,
      type="candle",
      style=estilo,
      title=f"\n{nombre_activo} — Temporalidad 15m | {titulo}",
      ylabel="Precio",
      figsize=(13, 6.5),
      returnfig=True,
      datetime_format="%H:%M",
      xrotation=0,
  )
  ax = axlist[0]

  # Mapear índices de tiempo a coordenadas de barras (0..N-1) en mplfinance
  tiempos = df_15m.index

  def idx_cercano(t_obj):
    diffs = [abs((t - t_obj).total_seconds()) for t in tiempos]
    return int( diffs.index(min(diffs)) ) if diffs else None

  # 1. Sombrear el tramo analizado en el reporte actual
  i_ini = idx_cercano(sub_start)
  i_fin = idx_cercano(sub_end)
  if i_ini is not None and i_fin is not None and i_fin >= i_ini:
    ax.axvspan(i_ini - 0.4, i_fin + 0.4, color="#2962ff", alpha=0.14, label="Tramo Evaluado")

  # 2. Líneas Horizontales (PDH, PDL, IB High, IB Low)
  n_bars = len(df_15m)
  if pd.notna(pdh):
    ax.axhline(pdh, color="#ef5350", linestyle="--", linewidth=1.2, alpha=0.85)
    ax.text(n_bars - 1, pdh, f" PDH {pdh:.2f}", color="#ef5350", fontsize=8, va="bottom", fontweight="bold")
  if pd.notna(pdl):
    ax.axhline(pdl, color="#26a69a", linestyle="--", linewidth=1.2, alpha=0.85)
    ax.text(n_bars - 1, pdl, f" PDL {pdl:.2f}", color="#26a69a", fontsize=8, va="top", fontweight="bold")
  if pd.notna(ib_high):
    ax.axhline(ib_high, color="#ab47bc", linestyle=":", linewidth=1.3, alpha=0.9)
    ax.text(n_bars - 1, ib_high, f" IBH {ib_high:.2f}", color="#ce93d8", fontsize=8, va="bottom")
  if pd.notna(ib_low):
    ax.axhline(ib_low, color="#ab47bc", linestyle=":", linewidth=1.3, alpha=0.9)
    ax.text(n_bars - 1, ib_low, f" IBL {ib_low:.2f}", color="#ce93d8", fontsize=8, va="top")

  # 3. Etiquetas de Apertura de Sesión (AS, LND, NY) con línea vertical
  rango_grafico = float(df_15m["High"].max() - df_15m["Low"].min())
  offset_y = rango_grafico * 0.08 if rango_grafico > 0 else 5.0

  sesiones_tags = [
      ("AS", t_as, "#2196f3"),
      ("LND", t_lnd, "#ff9800"),
      ("NY", t_ny, "#4caf50"),
  ]
  for tag_txt, t_ses, col_hex in sesiones_tags:
    if len(tiempos) > 0 and tiempos[0] <= t_ses <= tiempos[-1]:
      ix = idx_cercano(t_ses)
      if ix is not None:
        h_val = float(df_15m["High"].iloc[ix])
        o_val = float(df_15m["Open"].iloc[ix])
        ax.annotate(
            f"{tag_txt} {o_val:.2f}",
            xy=(ix, h_val),
            xytext=(ix, h_val + offset_y),
            ha="center",
            color="white",
            fontsize=8,
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.25", fc=col_hex, ec="none", alpha=0.9),
            arrowprops=dict(arrowstyle="-", color=col_hex, linestyle="dashed", lw=1),
        )

  # 4. Marcar el Máximo y Mínimo del Tramo Analizado
  sub_df = df_15m[(df_15m.index >= sub_start) & (df_15m.index <= sub_end)]
  if not sub_df.empty:
    t_max = sub_df["High"].idxmax()
    t_min = sub_df["Low"].idxmin()
    ix_max = idx_cercano(t_max)
    ix_min = idx_cercano(t_min)
    val_max = float(sub_df["High"].max())
    val_min = float(sub_df["Low"].min())

    if ix_max is not None:
      ax.annotate(
          f"Máx Tramo: {val_max:.2f}",
          xy=(ix_max, val_max),
          xytext=(ix_max, val_max + offset_y * 0.65),
          ha="center",
          color="#ffd54f",
          fontsize=8,
          fontweight="bold",
          arrowprops=dict(arrowstyle="->", color="#ffd54f", lw=1.2),
      )
    if ix_min is not None:
      ax.annotate(
          f"Mín Tramo: {val_min:.2f}",
          xy=(ix_min, val_min),
          xytext=(ix_min, val_min - offset_y * 0.75),
          ha="center",
          color="#4fc3f7",
          fontsize=8,
          fontweight="bold",
          arrowprops=dict(arrowstyle="->", color="#4fc3f7", lw=1.2),
      )

  buf = io.BytesIO()
  fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor="#131722")
  plt.close(fig)
  buf.seek(0)
  return buf


def enviar_reporte(num_reporte):
  if not DISCORD_WEBHOOK_URL:
    print("Error: No se configuró el secret DISCORD_WEBHOOK_URL en GitHub.")
    sys.exit(1)

  ahora_ny = datetime.datetime.now(TZ_NY)
  hoy = ahora_ny.date()
  ayer = hoy - datetime.timedelta(days=1)

  t_1800_prev = TZ_NY.localize(datetime.datetime.combine(ayer, datetime.time(18, 0)))
  t_0200_hoy = TZ_NY.localize(datetime.datetime.combine(hoy, datetime.time(2, 0)))
  t_0800_hoy = TZ_NY.localize(datetime.datetime.combine(hoy, datetime.time(8, 0)))
  t_0830_hoy = TZ_NY.localize(datetime.datetime.combine(hoy, datetime.time(8, 30)))
  t_0930_hoy = TZ_NY.localize(datetime.datetime.combine(hoy, datetime.time(9, 30)))
  t_1030_hoy = TZ_NY.localize(datetime.datetime.combine(hoy, datetime.time(10, 30)))
  t_1200_hoy = TZ_NY.localize(datetime.datetime.combine(hoy, datetime.time(12, 0)))
  t_1600_hoy = TZ_NY.localize(datetime.datetime.combine(hoy, datetime.time(16, 0)))
  t_1700_hoy = TZ_NY.localize(datetime.datetime.combine(hoy, datetime.time(17, 0)))

  for nombre_activo, ticker in ACTIVOS.items():
    df_15m = yf.download(ticker, period="5d", interval="15m", prepost=True, progress=False)
    if df_15m.empty:
      continue
    if isinstance(df_15m.columns, pd.MultiIndex):
      df_15m.columns = df_15m.columns.get_level_values(0)
    df_15m.index = df_15m.index.tz_convert(TZ_NY)

    t_1800_anteprev = t_1800_prev - datetime.timedelta(days=1)
    df_prev_day = df_15m[(df_15m.index >= t_1800_anteprev) & (df_15m.index < t_1800_prev)]
    pdh = float(df_prev_day["High"].max()) if not df_prev_day.empty else float("nan")
    pdl = float(df_prev_day["Low"].min()) if not df_prev_day.empty else float("nan")
    pdc = float(df_prev_day["Close"].iloc[-1]) if not df_prev_day.empty else float("nan")

    df_dia = df_15m[df_15m.index >= t_1800_prev]
    if df_dia.empty:
      df_dia = df_15m.tail(65)
      t_1800_prev = df_dia.index[0]

    day_open = float(df_dia["Open"].iloc[0])
    day_close = float(df_dia["Close"].iloc[-1])
    day_high = float(df_dia["High"].max())
    day_low = float(df_dia["Low"].min())

    df_as = df_dia[(df_dia.index >= t_1800_prev) & (df_dia.index < t_0200_hoy)]
    as_open = float(df_as["Open"].iloc[0]) if not df_as.empty else day_open
    as_close = float(df_as["Close"].iloc[-1]) if not df_as.empty else float("nan")

    df_lnd = df_dia[(df_dia.index >= t_0200_hoy) & (df_dia.index < t_0800_hoy)]
    lnd_open = float(df_lnd["Open"].iloc[0]) if not df_lnd.empty else float("nan")
    lnd_close = float(df_lnd["Close"].iloc[-1]) if not df_lnd.empty else float("nan")

    df_ny = df_dia[(df_dia.index >= t_0930_hoy) & (df_dia.index <= t_1600_hoy)]
    ny_open = float(df_ny["Open"].iloc[0]) if not df_ny.empty else float("nan")
    ny_close = float(df_ny["Close"].iloc[-1]) if not df_ny.empty else float("nan")

    df_ib = df_dia[(df_dia.index >= t_0930_hoy) & (df_dia.index < t_1030_hoy)]
    ib_high = float(df_ib["High"].max()) if not df_ib.empty else float("nan")
    ib_low = float(df_ib["Low"].min()) if not df_ib.empty else float("nan")

    df_r1 = df_dia[(df_dia.index >= t_1800_prev) & (df_dia.index <= t_0830_hoy)]
    r1_high = float(df_r1["High"].max()) if not df_r1.empty else float("nan")
    r1_low = float(df_r1["Low"].min()) if not df_r1.empty else float("nan")

    if num_reporte == 1:
      titulo = "REPORTE 1 (08:30 AM) | OVERNIGHT: 18:00 PM - 08:30 AM"
      tramo_nombre = "18:00 PM (Día Previo) a 08:30 AM"
      sub_start, sub_end = t_1800_prev, t_0830_hoy
      sub = df_r1
      ref_h, ref_l, ref_n = pdh, pdl, "Día Previo (PDH/PDL)"
    elif num_reporte == 2:
      titulo = "REPORTE 2 (12:00 PM) | MAÑANA NY: 08:30 AM - 12:00 PM"
      tramo_nombre = "08:30 AM a 12:00 PM (Apertura RTH + Balance Inicial)"
      sub_start, sub_end = t_0830_hoy, t_1200_hoy
      sub = df_dia[(df_dia.index >= t_0830_hoy) & (df_dia.index <= t_1200_hoy)]
      ref_h, ref_l, ref_n = r1_high, r1_low, "Overnight (18:00-08:30)"
    else:
      titulo = "REPORTE 3 (05:00 PM) | TARDE & CIERRE: 12:00 PM - 05:00 PM"
      tramo_nombre = "12:00 PM a 05:00 PM (Tarde + Cierre del Día)"
      sub_start, sub_end = t_1200_hoy, t_1700_hoy
      sub = df_dia[(df_dia.index >= t_1200_hoy) & (df_dia.index <= t_1700_hoy)]
      ref_h, ref_l, ref_n = ib_high, ib_low, "Balance Inicial (IB)"

    if sub.empty:
      sub = df_dia
      sub_start, sub_end = df_dia.index[0], df_dia.index[-1]

    s_open = float(sub["Open"].iloc[0])
    s_close = float(sub["Close"].iloc[-1])
    s_high = float(sub["High"].max())
    s_low = float(sub["Low"].min())

    est, ext, rng, c_pos = analizar_pa(s_open, s_high, s_low, s_close, ref_h, ref_l, ref_n)
    cambio_tramo = s_close - s_open
    signo_tramo = "+" if cambio_tramo >= 0 else ""

    cambio_dia = day_close - day_open
    signo_dia = "+" if cambio_dia >= 0 else ""

    ib_bloque = ""
    if num_reporte in (2, 3) and pd.notna(ib_high):
      estado_ib = evaluar_ib(
          ib_high,
          ib_low,
          float(df_ny["High"].max()) if not df_ny.empty else s_high,
          float(df_ny["Low"].min()) if not df_ny.empty else s_low,
          s_close,
      )
      ib_bloque = (
          "━━━━━━━━━━━━━━━━━━━━━━\n"
          "⚖️ **Balance Inicial (09:30 - 10:30 NY):**\n"
          f"• **IB High:** {fmt(ib_high)} | **IB Low:** {fmt(ib_low)} |"
          f" **Rango IB:** {fmt(ib_high - ib_low)} pts\n"
          f"• **Lectura IB:** {estado_ib}\n"
      )

    msg = (
        f"📊 **{titulo} | {nombre_activo}** ({ahora_ny.strftime('%Y-%m-%d %H:%M')} NY)\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕒 **Tramo Analizado:** {tramo_nombre}\n"
        f"🔹 **Apertura Tramo:** {fmt(s_open)} | **Cierre Tramo:** {fmt(s_close)} ({signo_tramo}{fmt(cambio_tramo)} pts)\n"
        f"📈 **Máximo Tramo:** {fmt(s_high)} | **Mínimo Tramo:** {fmt(s_low)} | **Rango:** {fmt(rng)} pts\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🌍 **Registro de Aperturas y Cierres (Día y Sesiones):**\n"
        f"• **Día Operativo (18:00 - 17:00):** Open: {fmt(day_open)} | Cierre Actual/Día: {fmt(day_close)} ({signo_dia}{fmt(cambio_dia)} pts) | Rango Día: {fmt(day_high - day_low)} pts\n"
        f"• **Sesión AS (18:00 - 02:00):** Open: {fmt(as_open)} | Close: {fmt(as_close)}\n"
        f"• **Sesión LND (02:00 - 08:00):** Open: {fmt(lnd_open)} | Close: {fmt(lnd_close)}\n"
        f"• **Sesión NY RTH (09:30 - 16:00):** Open: {fmt(ny_open)} | Close: {fmt(ny_close)}\n"
        f"• **Referencia Día Previo:** PDH: {fmt(pdh)} | PDL: {fmt(pdl)} | PDC: {fmt(pdc)}\n"
        f"{ib_bloque}"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🧠 **Análisis Price Action Clásico del Tramo:**\n"
        f"• **Estructura:** {est}\n"
        f"• **Ubicación del Cierre:** {c_pos:.1f}% del rango del tramo (0%=Mín, 100%=Máx)\n"
        f"• **Acción en S/R ({ref_n}):** {ext}"
    )

    # Generar imagen 15m del día operativo actual
    img_buffer = generar_imagen_15m(
        df_dia,
        nombre_activo,
        titulo,
        sub_start,
        sub_end,
        pdh,
        pdl,
        ib_high,
        ib_low,
        t_1800_prev,
        t_0200_hoy,
        t_0930_hoy,
    )

    files = {"file": (f"grafico_15m_{ticker}.png", img_buffer, "image/png")}
    res = requests.post(DISCORD_WEBHOOK_URL, data={"content": msg}, files=files)
    print(f"Enviado {nombre_activo} con imagen 15m - Status: {res.status_code}")


if __name__ == "__main__":
  if REPORTE_MANUAL in ("1", "2", "3"):
    enviar_reporte(int(REPORTE_MANUAL))
    sys.exit(0)

  ahora = datetime.datetime.now(TZ_NY)
  minutos_totales = ahora.hour * 60 + ahora.minute

  if abs(minutos_totales - (8 * 60 + 30)) <= 25:
    enviar_reporte(1)
  elif abs(minutos_totales - (12 * 60 + 0)) <= 25:
    enviar_reporte(2)
  elif abs(minutos_totales - (17 * 60 + 0)) <= 25:
    enviar_reporte(3)
  else:
    print(f"Hora actual en NY ({ahora.strftime('%H:%M')}) fuera de ventana.")
