import crc from "crc";
import QRCode from "qrcode";

const staticQris = process.env.GOPAY_QRIS_STRING;
const amount = Number(process.argv[2]);

if (!staticQris || !Number.isInteger(amount) || amount < 1) {
  throw new Error("GOPAY_QRIS_STRING atau nominal QRIS tidak valid.");
}

function convertCRC16(str) {
  const crc16 = crc.crc16ccitt(Buffer.from(str, "utf8")).toString(16).toUpperCase();
  return ("0000" + crc16).slice(-4);
}

function buildDynamicQris(staticString, nominal) {
  const data = staticString.endsWith("6304") ? staticString : staticString.slice(0, -4);
  const step1 = data.replace("010211", "010212");
  if (!step1.includes("5802ID")) {
    throw new Error("Format QRIS tidak valid.");
  }
  const [before, after] = step1.split("5802ID");
  const nominalField = "54" + String(String(nominal).length).padStart(2, "0") + nominal;
  return before + nominalField + "5802ID" + after + convertCRC16(before + nominalField + "5802ID" + after);
}

const dynamicQris = buildDynamicQris(staticQris, amount);
const dataUrl = await QRCode.toDataURL(dynamicQris, {
  scale: 8,
  errorCorrectionLevel: "M",
});
const imageBase64 = dataUrl.split(",")[1];

process.stdout.write(JSON.stringify({
  amount,
  qris: dynamicQris,
  image_base64: imageBase64,
}));
