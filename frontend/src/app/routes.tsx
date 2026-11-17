import { createBrowserRouter } from "react-router";
import {
  AppShell,
  BrowsePage,
  DiscoverPage,
  FuturePage,
  PaperDetail,
  SearchPage,
  TrendingPage,
} from "./screens";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: AppShell,
    children: [
      { index: true, Component: DiscoverPage },
      { path: "search", Component: SearchPage },
      { path: "categories", Component: BrowsePage },
      { path: "categories/:category", Component: SearchPage },
      { path: "trending", Component: TrendingPage },
      { path: "saved", element: <FuturePage type="saved" /> },
      { path: "history", element: <FuturePage type="history" /> },
      { path: "paper/:id", Component: PaperDetail },
    ],
  },
]);
