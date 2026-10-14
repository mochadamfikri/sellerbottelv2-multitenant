import { useEffect, useState } from "react";
import { useTenantApi } from "../lib/tenantApi";

export default function TenantImage({ src, ...props }) {
  const api = useTenantApi();
  const [url, setUrl] = useState("");
  useEffect(() => {
    if (!src?.startsWith("/api/public/tenant/full/")) {
      setUrl(src || "");
      return;
    }
    let objectUrl;
    let cancelled = false;
    setUrl("");
    api.get(src.slice(4), { responseType: "blob" }).then(({ data }) => {
      if (!cancelled) {
        objectUrl = URL.createObjectURL(data);
        setUrl(objectUrl);
      }
    }).catch(() => setUrl(""));
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [api, src]);
  return url ? <img src={url} {...props} alt={props.alt || ""} /> : null;
}
