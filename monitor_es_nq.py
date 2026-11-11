import datetime
import os
import sys
import pandas as pd
import pytz
import requests
import yfinance as yf

# Lee el Webhook desde los Secrets de GitHub Actions
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


def enviar_reporte(num_reporte):
  if not DISCORD_WEBHOOK_URL:
    print("Error: No se configuró el secret DISCORD_WEBHOOK_URL en GitHub.")
    sys.exit(1)

  ahora_ny = datetime.datetime.now(TZ_NY)
  hoy = ahora_ny.date()
  ayer = hoy - datetime.timedelta(days=1)

  t_1800_prev = TZ_NY.localize(
      datetime.datetime.combine(ayer, datetime.time(18, 0))
  )
  t_0200_hoy = TZ_NY.localize(
      datetime.datetime.combine(hoy, datetime.time(2, 0))
  )
  t_0800_hoy = TZ_NY.localize(
      datetime.datetime.combine(hoy, datetime.time(8, 0))
  )
  t_0830_hoy = TZ_NY.localize(
      datetime.datetime.combine(hoy, datetime.time(8, 30))
  )
  t_0930_hoy = TZ_NY.localize(
      datetime.datetime.combine(hoy, datetime.time(9, 30))
  )
  t_1030_hoy = TZ_NY.localize(
      datetime.datetime.combine(hoy, datetime.time(10, 30))
  )
  t_1200_hoy = TZ_NY.localize(
      datetime.datetime.combine(hoy, datetime.time(12, 0))
  )
  t_1600_hoy = TZ_NY.localize(
      datetime.datetime.combine(hoy, datetime.time(16, 0))
  )
  t_1700_hoy = TZ_NY.localize(
      datetime.datetime.combine(hoy, datetime.time(17, 0))
  )

  for nombre_activo, ticker in ACTIVOS.items():
    df = yf.download(
        ticker, period="5d", interval="5m", prepost=True, progress=False
    )
    if df.empty:
      continue
    if isinstance(df.columns, pd.MultiIndex):
      df.columns = df.columns.get_level_values(0)
    df.index = df.index.tz_convert(TZ_NY)

    t_1800_anteprev = t_1800_prev - datetime.timedelta(days=1)
    df_prev_day = df[(df.index >= t_1800_anteprev) & (df.index < t_1800_prev)]
    pdh = df_prev_day["High"].max() if not df_prev_day.empty else float("nan")
    pdl = df_prev_day["Low"].min() if not df_prev_day.empty else float("nan")
    pdc = (
        df_prev_day["Close"].iloc[-1] if not df_prev_day.empty else float("nan")
    )

    df_dia = df[df.index >= t_1800_prev]
    if df_dia.empty:
      df_dia = df.tail(100)

    day_open = float(df_dia["Open"].iloc[0])
    day_close = float(df_dia["Close"].iloc[-1])
    day_high = float(df_dia["High"].max())
    day_low = float(df_dia["Low"].min())

    df_as = df_dia[(df_dia.index >= t_1800_prev) & (df_dia.index < t_0200_hoy)]
    as_open = float(df_as["Open"].iloc[0]) if not df_as.empty else day_open
    as_close = (
        float(df_as["Close"].iloc[-1]) if not df_as.empty else float("nan")
    )

    df_lnd = df_dia[(df_dia.index >= t_0200_hoy) & (df_dia.index < t_0800_hoy)]
    lnd_open = (
        float(df_lnd["Open"].iloc[0]) if not df_lnd.empty else float("nan")
    )
    lnd_close = (
        float(df_lnd["Close"].iloc[-1]) if not df_lnd.empty else float("nan")
    )

    df_ny = df_dia[(df_dia.index >= t_0930_hoy) & (df_dia.index <= t_1600_hoy)]
    ny_open = float(df_ny["Open"].iloc[0]) if not df_ny.empty else float("nan")
    ny_close = (
        float(df_ny["Close"].iloc[-1]) if not df_ny.empty else float("nan")
    )

    df_ib = df_dia[(df_dia.index >= t_0930_hoy) & (df_dia.index < t_1030_hoy)]
    ib_high = float(df_ib["High"].max()) if not df_ib.empty else float("nan")
    ib_low = float(df_ib["Low"].min()) if not df_ib.empty else float("nan")

    df_r1 = df_dia[(df_dia.index >= t_1800_prev) & (df_dia.index <= t_0830_hoy)]
    r1_high = float(df_r1["High"].max()) if not df_r1.empty else float("nan")
    r1_low = float(df_r1["Low"].min()) if not df_r1.empty else float("nan")

    if num_reporte == 1:
      titulo = "REPORTE 1 (08:30 AM) | OVERNIGHT: 18:00 PM - 08:30 AM"
      tramo_nombre = "18:00 PM (Día Previo) a 08:30 AM"
      sub = df_r1
      ref_h, ref_l, ref_n = pdh, pdl, "Día Previo (PDH/PDL)"
    elif num_reporte == 2:
      titulo = "REPORTE 2 (12:00 PM) | MAÑANA NY: 08:30 AM - 12:00 PM"
      tramo_nombre = "08:30 AM a 12:00 PM (Apertura RTH + Balance Inicial)"
      sub = df_dia[(df_dia.index >= t_0830_hoy) & (df_dia.index <= t_1200_hoy)]
      ref_h, ref_l, ref_n = r1_high, r1_low, "Overnight (18:00-08:30)"
    else:
      titulo = "REPORTE 3 (05:00 PM) | TARDE & CIERRE: 12:00 PM - 05:00 PM"
      tramo_nombre = "12:00 PM a 05:00 PM (Tarde + Cierre del Día)"
      sub = df_dia[(df_dia.index >= t_1200_hoy) & (df_dia.index <= t_1700_hoy)]
      ref_h, ref_l, ref_n = ib_high, ib_low, "Balance Inicial (IB)"

    if sub.empty:
      sub = df_dia

    s_open = float(sub["Open"].iloc[0])
    s_close = float(sub["Close"].iloc[-1])
    s_high = float(sub["High"].max())
    s_low = float(sub["Low"].min())

    est, ext, rng, c_pos = analizar_pa(
        s_open, s_high, s_low, s_close, ref_h, ref_l, ref_n
    )
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
        f"📊 **{titulo} | {nombre_activo}**"
        f" ({ahora_ny.strftime('%Y-%m-%d %H:%M')} NY)\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕒 **Tramo Analizado:** {tramo_nombre}\n"
        f"🔹 **Apertura Tramo:** {fmt(s_open)} | **Cierre Tramo:**"
        f" {fmt(s_close)} ({signo_tramo}{fmt(cambio_tramo)} pts)\n"
        f"📈 **Máximo Tramo:** {fmt(s_high)} | **Mínimo Tramo:** {fmt(s_low)} |"
        f" **Rango:** {fmt(rng)} pts\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🌍 **Registro de Aperturas y Cierres (Día y Sesiones):**\n"
        f"• **Día Operativo (18:00 - 17:00):** Open: {fmt(day_open)} | Cierre"
        f" Actual/Día: {fmt(day_close)} ({signo_dia}{fmt(cambio_dia)} pts) |"
        f" Rango Día: {fmt(day_high - day_low)} pts\n"
        f"• **Sesión AS (18:00 - 02:00):** Open: {fmt(as_open)} | Close:"
        f" {fmt(as_close)}\n"
        f"• **Sesión LND (02:00 - 08:00):** Open: {fmt(lnd_open)} | Close:"
        f" {fmt(lnd_close)}\n"
        f"• **Sesión NY RTH (09:30 - 16:00):** Open: {fmt(ny_open)} | Close:"
        f" {fmt(ny_close)}\n"
        f"• **Referencia Día Previo:** PDH: {fmt(pdh)} | PDL: {fmt(pdl)} | PDC:"
        f" {fmt(pdc)}\n"
        f"{ib_bloque}"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🧠 **Análisis Price Action Clásico del Tramo:**\n"
        f"• **Estructura:** {est}\n"
        f"• **Ubicación del Cierre:** {c_pos:.1f}% del rango del tramo (0%=Mín,"
        " 100%=Máx)\n"
        f"• **Acción en S/R ({ref_n}):** {ext}"
    )

    res = requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
    print(
        f"Enviado {nombre_activo} - Status: {res.status_code}"
    )


if __name__ == "__main__":
  # 1. Si se disparó manualmente desde el botón de GitHub Actions
  if REPORTE_MANUAL in ("1", "2", "3"):
    print(f"Ejecución manual solicitada: Reporte {REPORTE_MANUAL}")
    enviar_reporte(int(REPORTE_MANUAL))
    sys.exit(0)

  # 2. Si se disparó automáticamente por horario (cron), verificamos la hora exacta en NY
  ahora = datetime.datetime.now(TZ_NY)
  minutos_totales = ahora.hour * 60 + ahora.minute

  # Ventanas de tolerancia de ±25 min para absorber cualquier retraso del cron de GitHub
  if abs(minutos_totales - (8 * 60 + 30)) <= 25:
    enviar_reporte(1)
  elif abs(minutos_totales - (12 * 60 + 0)) <= 25:
    enviar_reporte(2)
  elif abs(minutos_totales - (17 * 60 + 0)) <= 25:
    enviar_reporte(3)
  else:
    print(
        f"Hora actual en NY ({ahora.strftime('%H:%M')}) fuera de ventana de"
        " reporte (ciclo DST ignorado)."
    )
