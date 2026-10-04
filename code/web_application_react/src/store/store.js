import { configureStore } from "@reduxjs/toolkit";
import listingsReducer from "./listingsSlice";

export const store = configureStore({
  reducer: {
    listings: listingsReducer,
  },
});