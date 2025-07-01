import { createStyles } from "@mantine/core";

export const useTableStyles = createStyles((theme) => ({
  primary: {
    display: "inline-block",
    [theme.fn.smallerThan("sm")]: {
      minWidth: "12rem",
    },
  },
  noWrap: {
    whiteSpace: "nowrap",
  },
  select: {
    display: "inline-block",
    [theme.fn.smallerThan("sm")]: {
      minWidth: "10rem",
    },
  },
  width10em: {
    width: "10em",
  },
  width9em: {
    width: "9em",
  },
  width8em: {
    width: "8em",
  },
  width7em: {
    width: "7em",
  },
  width6em: {
    width: "6em",
  },
  width5em: {
    width: "5em",
  },
  width4em: {
    width: "4em",
  },
  width3em: {
    width: "3em",
  },
  width2em: {
    width: "2em",
  },
  width1em: {
    width: "1em",
  },
}));
