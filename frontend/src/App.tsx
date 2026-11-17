import { RouterProvider } from "react-router";
import { router } from "./app/routes";

export default function App() {
  return <RouterProvider router={router} />;
}
