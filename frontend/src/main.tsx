import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { getToken } from "./lib/api";
import Dashboard from "./routes/Dashboard";
import Shell from "./components/Shell";
import Alerts from "./routes/Alerts";
import Beds from "./routes/Beds";
import Book from "./routes/Book";
import GoldenHour from "./routes/GoldenHour";
import Impact from "./routes/Impact";
import NetworkMap from "./routes/NetworkMap";
import Queues from "./routes/Queues";
import Scenarios from "./routes/Scenarios";
import PresenceBoard from "./routes/PresenceBoard";
import Referrals from "./routes/Referrals";
import DevUI from "./routes/DevUI";
import Login from "./routes/Login";
import MyQueue from "./routes/MyQueue";
import PatientLogin from "./routes/PatientLogin";
import "./styles/tokens.css";

function RequireAuth({ children }: { children: React.ReactElement }) {
  return getToken() ? children : <Navigate to="/login" replace />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={new QueryClient()}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/patient" element={<PatientLogin />} />
          <Route
            element={
              <RequireAuth>
                <Shell />
              </RequireAuth>
            }
          >
            <Route path="/" element={<PresenceBoard />} />
            <Route path="/queue" element={<Queues />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/map" element={<NetworkMap />} />
            <Route path="/beds" element={<Beds />} />
            <Route path="/referrals" element={<Referrals />} />
            <Route path="/golden-hour" element={<GoldenHour />} />
            <Route path="/impact" element={<Impact />} />
            <Route path="/scenarios" element={<Scenarios />} />
            <Route path="/events" element={<Dashboard />} />
            <Route path="/dev/ui" element={<DevUI />} />
          </Route>
          <Route
            path="/book"
            element={
              <RequireAuth>
                <Book />
              </RequireAuth>
            }
          />
          {/* Patient surface, so no Shell: the dark dock is command-centre chrome (§9a). */}
          <Route
            path="/my-queue"
            element={
              <RequireAuth>
                <MyQueue />
              </RequireAuth>
            }
          />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
