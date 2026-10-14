import axios from "axios";
import { createContext, useContext } from "react";

export const TenantApiContext = createContext(null);

export function createTenantApi(token = "") {
  return axios.create({
    baseURL: process.env.REACT_APP_BACKEND_URL
      ? `${process.env.REACT_APP_BACKEND_URL.replace(/\/$/, "")}/api`
      : "/api",
    withCredentials: false,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
}

export function clearTenantApi(api) {
  delete api.defaults.headers.common.Authorization;
  delete api.defaults.headers.Authorization;
}

export function useTenantApi() {
  const api = useContext(TenantApiContext);
  if (!api) throw new Error("Tenant management requires a tenant session");
  return api;
}
