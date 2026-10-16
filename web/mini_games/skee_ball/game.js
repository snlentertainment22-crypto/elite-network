import * as THREE
from "https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.js";


/* ======================================================
   BASIC SCENE
   ====================================================== */

const mount =
  document.getElementById("game");

const scene =
  new THREE.Scene();

scene.background =
  new THREE.Color(0x02050a);

scene.fog =
  new THREE.FogExp2(
    0x02050a,
    0.035
  );


const camera =
  new THREE.PerspectiveCamera(
    50,
    window.innerWidth /
    window.innerHeight,
    .1,
    100
  );

camera.position.set(
  0,
  5.6,
  13.5
);

camera.lookAt(
  0,
  1.8,
  -4
);


const renderer =
  new THREE.WebGLRenderer({
    antialias: true
  });

renderer.setSize(
  window.innerWidth,
  window.innerHeight
);

renderer.setPixelRatio(
  Math.min(
    window.devicePixelRatio,
    2
  )
);

renderer.shadowMap.enabled =
  true;

renderer.shadowMap.type =
  THREE.PCFSoftShadowMap;

renderer.outputColorSpace =
  THREE.SRGBColorSpace;

renderer.toneMapping =
  THREE.ACESFilmicToneMapping;

renderer.toneMappingExposure =
  1.25;

mount.appendChild(
  renderer.domElement
);


/* ======================================================
   LIGHTING
   ====================================================== */

const ambient =
  new THREE.AmbientLight(
    0x739bc4,
    1.1
  );

scene.add(ambient);


const mainLight =
  new THREE.DirectionalLight(
    0xffffff,
    4
  );

mainLight.position.set(
  2,
  9,
  7
);

mainLight.castShadow =
  true;

scene.add(mainLight);


const blueLight =
  new THREE.PointLight(
    0x0099ff,
    30,
    16
  );

blueLight.position.set(
  -5,
  4,
  1
);

scene.add(blueLight);


const pinkLight =
  new THREE.PointLight(
    0xff2055,
    24,
    15
  );

pinkLight.position.set(
  5,
  3,
  -3
);

scene.add(pinkLight);


/* ======================================================
   FLOOR
   ====================================================== */

const floor =
  new THREE.Mesh(
    new THREE.PlaneGeometry(
      40,
      40
    ),
    new THREE.MeshStandardMaterial({
      color: 0x05090f,
      roughness: .75,
      metalness: .2
    })
  );

floor.rotation.x =
  -Math.PI / 2;

floor.position.y =
  -.08;

floor.receiveShadow =
  true;

scene.add(floor);


/* ======================================================
   SKEE BALL MACHINE BASE
   ====================================================== */

const machine =
  new THREE.Group();

scene.add(machine);


const baseMaterial =
  new THREE.MeshStandardMaterial({
    color: 0x111a25,
    roughness: .3,
    metalness: .75
  });


const laneMaterial =
  new THREE.MeshStandardMaterial({
    color: 0x876b45,
    roughness: .42,
    metalness: .12
  });


const railMaterial =
  new THREE.MeshStandardMaterial({
    color: 0x151d28,
    roughness: .2,
    metalness: .85
  });


/* main cabinet */

const cabinet =
  new THREE.Mesh(
    new THREE.BoxGeometry(
      6.4,
      .65,
      17
    ),
    baseMaterial
  );

cabinet.position.set(
  0,
  .3,
  -1
);

cabinet.castShadow = true;
cabinet.receiveShadow = true;

machine.add(cabinet);


/* wood lane */

const lane =
  new THREE.Mesh(
    new THREE.BoxGeometry(
      5.5,
      .12,
      13.8
    ),
    laneMaterial
  );

lane.position.set(
  0,
  .68,
  .5
);

lane.receiveShadow =
  true;

machine.add(lane);


/* lane strips */

for (
  let i = -2;
  i <= 2;
  i++
) {

  const strip =
    new THREE.Mesh(
      new THREE.BoxGeometry(
        .018,
        .012,
        13.3
      ),
      new THREE.MeshBasicMaterial({
        color:
          i === 0
            ? 0x7bcfff
            : 0xffffff,
        transparent: true,
        opacity:
          i === 0
            ? .38
            : .08
      })
    );

  strip.position.set(
    i * 1.05,
    .75,
    .5
  );

  machine.add(strip);

}


/* glowing side rails */

function createRail(x) {

  const rail =
    new THREE.Mesh(
      new THREE.BoxGeometry(
        .16,
        .38,
        14.4
      ),
      railMaterial
    );

  rail.position.set(
    x,
    .92,
    .25
  );

  rail.castShadow = true;

  machine.add(rail);


  const glow =
    new THREE.Mesh(
      new THREE.BoxGeometry(
        .035,
        .055,
        14.1
      ),
      new THREE.MeshBasicMaterial({
        color:
          x < 0
            ? 0x009dff
            : 0xff2b61
      })
    );

  glow.position.set(
    x * .995,
    1.13,
    .25
  );

  machine.add(glow);

}


createRail(-2.83);
createRail(2.83);


/* ======================================================
   RAMP
   ====================================================== */

const ramp =
  new THREE.Mesh(
    new THREE.BoxGeometry(
      5.45,
      .18,
      3.3
    ),
    laneMaterial
  );

ramp.rotation.x =
  -THREE.MathUtils.degToRad(20);

ramp.position.set(
  0,
  1.22,
  -6.7
);

ramp.receiveShadow = true;
ramp.castShadow = true;

machine.add(ramp);


/* ======================================================
   TARGET BOARD
   ====================================================== */

const board =
  new THREE.Group();

board.position.set(
  0,
  2.35,
  -8.25
);

board.rotation.x =
  THREE.MathUtils.degToRad(-18);

machine.add(board);


const boardBack =
  new THREE.Mesh(
    new THREE.BoxGeometry(
      5.6,
      4.8,
      .28
    ),
    new THREE.MeshStandardMaterial({
      color: 0x101820,
      roughness: .28,
      metalness: .65
    })
  );

boardBack.position.z =
  -.18;

boardBack.castShadow = true;

board.add(boardBack);


/* ======================================================
   SCORE HOLES
   ====================================================== */

const holes = [];

function makeHole(
  x,
  y,
  radius,
  score,
  color
) {

  const group =
    new THREE.Group();

  group.position.set(
    x,
    y,
    0
  );


  const ring =
    new THREE.Mesh(
      new THREE.TorusGeometry(
        radius,
        .11,
        24,
        64
      ),
      new THREE.MeshStandardMaterial({
        color,
        emissive: color,
        emissiveIntensity: 1.1,
        roughness: .28,
        metalness: .65
      })
    );

  ring.castShadow = true;

  group.add(ring);


  const hole =
    new THREE.Mesh(
      new THREE.CircleGeometry(
        radius * .83,
        48
      ),
      new THREE.MeshBasicMaterial({
        color: 0x010204
      })
    );

  hole.position.z =
    -.02;

  group.add(hole);


  board.add(group);


  holes.push({
    x,
    y,
    radius,
    score,
    ring
  });

}


/*
  lower large holes
*/

makeHole(
  -1.65,
  -.6,
  .72,
  20,
  0x009dff
);

makeHole(
  0,
  -.75,
  .78,
  30,
  0x26d6ff
);

makeHole(
  1.65,
  -.6,
  .72,
  20,
  0xff315f
);


/*
  middle
*/

makeHole(
  -.85,
  1.0,
  .62,
  40,
  0x58dcff
);

makeHole(
  .85,
  1.0,
  .62,
  40,
  0xff5479
);


/*
  high bonus
*/

makeHole(
  0,
  2.02,
  .52,
  50,
  0xffdf63
);


/*
  top corners 100
*/

makeHole(
  -2.05,
  1.95,
  .42,
  100,
  0xffba38
);

makeHole(
  2.05,
  1.95,
  .42,
  100,
  0xffba38
);


/* ======================================================
   BALL
   ====================================================== */

const ball =
  new THREE.Mesh(
    new THREE.SphereGeometry(
      .26,
      32,
      32
    ),
    new THREE.MeshStandardMaterial({
      color: 0xd8f5ff,
      emissive: 0x0f4660,
      emissiveIntensity: .45,
      roughness: .22,
      metalness: .15
    })
  );

ball.castShadow = true;

scene.add(ball);


/* ball glow */

const ballLight =
  new THREE.PointLight(
    0x55cfff,
    4,
    3
  );

scene.add(ballLight);


/* ======================================================
   GAME STATE
   ====================================================== */

let aim = 0;

let power = 0;

let charging = false;

let chargeDirection = 1;

let shooting = false;

let ballsRemaining = 3;

let score = 0;

let shotTime = 0;

let shotPower = 0;

let shotAim = 0;

let startPosition =
  new THREE.Vector3();

let velocity =
  new THREE.Vector3();


const playerNameElement =
  document.getElementById(
    "playerName"
  );

let networkSkeeState = null;
let networkTeamId = null;
let lastSkeeControlSeq = 0;


function setBallDotsFromNetwork(
  ballNumber,
  ballsRemaining
) {

  for (
    let i = 1;
    i <= 3;
    i++
  ) {

    const dot =
      document.getElementById(
        `ball${i}`
      );

    if (!dot) continue;

    if (i <= ballsRemaining) {
      dot.classList.add(
        "active"
      );
    } else {
      dot.classList.remove(
        "active"
      );
    }
  }
}


function applySkeeControl(
  mini
) {

  const command =
    mini.control || null;

  if (!command) {
    return;
  }

  const seq =
    Number(
      command.seq || 0
    );

  if (
    seq <=
    lastSkeeControlSeq
  ) {
    return;
  }

  lastSkeeControlSeq = seq;

  const action =
    command.action || "";


  if (
    action === "left" &&
    !shooting
  ) {

    aim -= .12;

    aim =
      THREE.MathUtils.clamp(
        aim,
        -1,
        1
      );

    return;
  }


  if (
    action === "right" &&
    !shooting
  ) {

    aim += .12;

    aim =
      THREE.MathUtils.clamp(
        aim,
        -1,
        1
      );

    return;
  }


  if (
    action === "charge_start" &&
    !shooting
  ) {

    charging = true;

    message.textContent =
      "CHARGING";

    return;
  }


  if (
    action === "throw" &&
    charging &&
    !shooting
  ) {

    charging = false;

    shootBall();
  }
}


async function reportSkeeResult(
  points
) {

  try {

    const response =
      await fetch(
        "/api/skee-result",
        {
          method: "POST",

          headers: {
            "Content-Type":
              "application/json"
          },

          body:
            JSON.stringify({
              points:
                Number(points || 0)
            }),

          cache:
            "no-store"
        }
      );

    const payload =
      await response.json();

    if (!payload.ok) {

      console.warn(
        "Skee-Ball score rejected:",
        payload.error
      );
    }

  } catch (error) {

    console.warn(
      "Skee-Ball score report error:",
      error
    );
  }
}


async function pollEliteSkeeState() {

  try {

    const response =
      await fetch(
        "/api/state",
        {
          cache: "no-store"
        }
      );

    const payload =
      await response.json();

    if (
      !payload.ok ||
      !payload.state
    ) {
      return;
    }

    const mini =
      payload.state.network &&
      payload.state.network.mini_game;

    if (
      !mini ||
      !mini.active ||
      mini.game_type !== "skee_ball"
    ) {

      playerNameElement.textContent =
        "WAITING...";

      return;
    }


    networkSkeeState = mini;

    applySkeeControl(
      mini
    );

    const team =
      mini.current_team || {};

    const newTeamId =
      team.id || null;


    if (
      newTeamId &&
      newTeamId !== networkTeamId
    ) {

      networkTeamId =
        newTeamId;

      resetGame();

    }


    playerNameElement.textContent =
      team.name || "WAITING...";


    const ballNumber =
      Number(
        mini.ball_number || 1
      );

    const ballsRemainingNetwork =
      Number(
        mini.balls_remaining || 0
      );


    setBallDotsFromNetwork(
      ballNumber,
      ballsRemainingNetwork
    );


    if (
      mini.phase === "between_turns"
    ) {

      message.textContent =
        "NEXT PLAYER";

    } else if (
      mini.phase === "turn"
    ) {

      message.textContent =
        `BALL ${ballNumber} OF ${mini.balls_per_team || 3}`;

    } else if (
      mini.phase === "outro"
    ) {

      message.textContent =
        "CHALLENGE COMPLETE";
    }

  } catch (error) {

    console.warn(
      "Skee-Ball network state error:",
      error
    );
  }
}


setInterval(
  pollEliteSkeeState,
  100
);

pollEliteSkeeState();


const scoreElement =
  document.getElementById(
    "score"
  );

const aimMarker =
  document.getElementById(
    "aimMarker"
  );

const powerFill =
  document.getElementById(
    "powerFill"
  );

const message =
  document.getElementById(
    "message"
  );

const popup =
  document.getElementById(
    "scorePopup"
  );

const gameOver =
  document.getElementById(
    "gameOver"
  );

const finalScore =
  document.getElementById(
    "finalScore"
  );

const playAgain =
  document.getElementById(
    "playAgain"
  );


function resetBall() {

  shooting = false;

  ball.position.set(
    aim * 1.7,
    .99,
    6.3
  );

  ball.rotation.set(
    0,
    0,
    0
  );

  ballLight.position.copy(
    ball.position
  );

  power = 0;

  powerFill.style.width =
    "0%";

  message.textContent =
    "READY";

}


function resetGame() {

  ballsRemaining = 3;

  score = 0;

  aim = 0;

  charging = false;

  chargeDirection = 1;

  scoreElement.textContent =
    "000";

  gameOver.classList.remove(
    "show"
  );

  document.querySelectorAll(
    ".ball-dot"
  ).forEach(
    dot => dot.classList.add(
      "active"
    )
  );

  resetBall();

}


resetGame();


/* ======================================================
   INPUT
   ====================================================== */

window.addEventListener(
  "keydown",
  event => {

    if (shooting) return;


    if (
      event.code === "KeyA"
    ) {

      aim -= .045;

    }


    if (
      event.code === "KeyD"
    ) {

      aim += .045;

    }


    aim =
      THREE.MathUtils.clamp(
        aim,
        -1,
        1
      );


    if (
      event.code === "Space" &&
      !event.repeat
    ) {

      event.preventDefault();

      charging = true;

      message.textContent =
        "CHARGING";

    }

  }
);


window.addEventListener(
  "keyup",
  event => {

    if (
      event.code === "Space" &&
      charging &&
      !shooting
    ) {

      event.preventDefault();

      charging = false;

      shootBall();

    }

  }
);


playAgain.addEventListener(
  "click",
  resetGame
);


/* ======================================================
   SHOOT
   ====================================================== */

function shootBall() {

  if (
    ballsRemaining <= 0
  ) {
    return;
  }


  shooting = true;

  shotTime = 0;

  shotPower = power;

  shotAim = aim;


  startPosition.set(
    aim * 1.7,
    .99,
    6.3
  );


  ball.position.copy(
    startPosition
  );


  /*
    horizontal movement:
    aim affects lane angle slightly
  */

  velocity.set(
    shotAim * .75,
    0,
    -(7.2 + shotPower * 5)
  );


  message.textContent =
    "ROLLING";

}


/* ======================================================
   SCORE
   ====================================================== */

function registerScore(points) {

  reportSkeeResult(
    points
  );

  score += points;

  scoreElement.textContent =
    String(score).padStart(
      3,
      "0"
    );


  popup.textContent =
    `+${points}`;

  popup.classList.remove(
    "show"
  );

  void popup.offsetWidth;

  popup.classList.add(
    "show"
  );


  message.textContent =
    points >= 100
      ? "JACKPOT!"
      : points >= 50
      ? "GREAT SHOT!"
      : "SCORE!";


  ballsRemaining--;


  const used =
    3 - ballsRemaining;

  const dot =
    document.getElementById(
      `ball${used}`
    );

  if (dot) {
    dot.classList.remove(
      "active"
    );
  }


  setTimeout(
    () => {

      if (
        ballsRemaining > 0
      ) {

        resetBall();

      }

      else {

        if (!networkSkeeState) {

          finalScore.textContent =
            String(score).padStart(
              3,
              "0"
            );

          gameOver.classList.add(
            "show"
          );
        }

      }

    },
    1100
  );

}


/* ======================================================
   MISS
   ====================================================== */

function registerMiss() {

  reportSkeeResult(
    0
  );

  message.textContent =
    "MISS";

  ballsRemaining--;


  const used =
    3 - ballsRemaining;

  const dot =
    document.getElementById(
      `ball${used}`
    );

  if (dot) {
    dot.classList.remove(
      "active"
    );
  }


  setTimeout(
    () => {

      if (
        ballsRemaining > 0
      ) {

        resetBall();

      }

      else {

        if (!networkSkeeState) {

          finalScore.textContent =
            String(score).padStart(
              3,
              "0"
            );

          gameOver.classList.add(
            "show"
          );
        }

      }

    },
    850
  );

}


/* ======================================================
   SHOT SIMULATION
   ====================================================== */

function updateShot(dt) {

  if (!shooting) {
    return;
  }


  shotTime += dt;


  /*
    Flat lane
  */

  if (
    ball.position.z > -5.2
  ) {

    ball.position.x +=
      velocity.x * dt;

    ball.position.z +=
      velocity.z * dt;

    ball.rotation.x -=
      velocity.z *
      dt *
      2.7;

  }


  /*
    Ramp area:
    launch upward
  */

  else if (
    ball.position.z > -7.15
  ) {

    ball.position.x +=
      velocity.x * dt;

    ball.position.z +=
      velocity.z * dt;

    ball.position.y +=
      3.6 *
      shotPower *
      dt;

    ball.rotation.x -=
      velocity.z *
      dt *
      2.7;

  }


  /*
    airborne toward target
  */

  else {

    velocity.y -=
      8.5 * dt;


    ball.position.x +=
      velocity.x * dt;

    ball.position.y +=
      velocity.y * dt;

    ball.position.z +=
      velocity.z *
      .45 *
      dt;

  }


  /*
    initial airborne impulse
  */

  if (
    shotTime > .55 &&
    shotTime < .55 + dt
  ) {

    velocity.y =
      4.1 +
      shotPower * 4.1;

  }


  ballLight.position.copy(
    ball.position
  );


  /*
    Detect approximate arrival at board.
  */

  if (
    ball.position.z <
    -8.05
  ) {

    const boardX =
      ball.position.x;

    const boardY =
      ball.position.y -
      board.position.y;


    let scored =
      null;


    /*
      Find closest scoring hole.
    */

    for (
      const hole
      of holes
    ) {

      const distance =
        Math.sqrt(
          Math.pow(
            boardX - hole.x,
            2
          ) +
          Math.pow(
            boardY - hole.y,
            2
          )
        );


      if (
        distance <
        hole.radius * 1.20
      ) {

        scored = hole;

        break;

      }

    }


    shooting = false;


    if (scored) {

      scored.ring.material
        .emissiveIntensity =
        4;


      setTimeout(
        () => {

          scored.ring.material
            .emissiveIntensity =
            1.1;

        },
        350
      );


      registerScore(
        scored.score
      );

    }

    else {

      registerMiss();

    }

  }


  /*
    safety timeout
  */

  if (
    shotTime > 3
  ) {

    shooting = false;

    registerMiss();

  }

}


/* ======================================================
   CAMERA REACTION
   ====================================================== */

let cameraTargetZ =
  13.5;

function updateCamera(dt) {

  if (shooting) {

    cameraTargetZ =
      THREE.MathUtils.lerp(
        cameraTargetZ,
        10.8,
        dt * 2.5
      );

  }

  else {

    cameraTargetZ =
      THREE.MathUtils.lerp(
        cameraTargetZ,
        13.5,
        dt * 3
      );

  }


  camera.position.z =
    cameraTargetZ;


  camera.lookAt(
    ball.position.x * .16,
    1.9,
    -4.3
  );

}


/* ======================================================
   LOOP
   ====================================================== */

let previousTime =
  performance.now();

function animate(now) {

  requestAnimationFrame(
    animate
  );


  let dt =
    (now - previousTime) /
    1000;

  previousTime = now;


  dt =
    Math.min(
      dt,
      .033
    );


  /*
    power oscillates while holding space
  */

  if (
    charging &&
    !shooting
  ) {

    power +=
      chargeDirection *
      dt *
      1.15;


    if (
      power >= 1
    ) {

      power = 1;

      chargeDirection = -1;

    }


    if (
      power <= 0
    ) {

      power = 0;

      chargeDirection = 1;

    }


    powerFill.style.width =
      `${power * 100}%`;

  }


  /*
    Ball position follows aim
    before shooting.
  */

  if (!shooting) {

    ball.position.x =
      THREE.MathUtils.lerp(
        ball.position.x,
        aim * 1.7,
        .16
      );

  }


  /*
    HUD aim
  */

  aimMarker.style.left =
    `${
      50 +
      aim * 46
    }%`;


  updateShot(dt);

  updateCamera(dt);


  /*
    subtle animated lighting
  */

  blueLight.intensity =
    27 +
    Math.sin(now * .0015) * 5;

  pinkLight.intensity =
    22 +
    Math.sin(
      now * .0015 + 2
    ) * 5;


  renderer.render(
    scene,
    camera
  );

}


requestAnimationFrame(
  animate
);


/* ======================================================
   RESIZE
   ====================================================== */

window.addEventListener(
  "resize",
  () => {

    camera.aspect =
      window.innerWidth /
      window.innerHeight;

    camera.updateProjectionMatrix();


    renderer.setSize(
      window.innerWidth,
      window.innerHeight
    );

  }
);