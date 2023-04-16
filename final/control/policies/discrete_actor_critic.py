import numpy as np
import torch
import torch.nn as nn

from final.tensor import KoopmanTensor

class DiscreteKoopmanPolicyIterationPolicy:
    """
        Compute the optimal policy for the given state using discrete Koopman policy iteration methodology.
    """

    def __init__(
        self,
        true_dynamics,
        gamma,
        regularization_lambda,
        koopman_model: KoopmanTensor,
        state_minimums,
        state_maximums,
        all_actions,
        cost,
        save_data_path,
        dt=1.0,
        learning_rate=0.003, # 3e-3
        w_hat_batch_size=2**14,
        seed=123,
        load_model=False,
        layer_1_dim=256,
        layer_2_dim=128
    ):
        """
            Constructor for the DiscreteKoopmanPolicyIterationPolicy class.

            INPUTS:
                true_dynamics - The true dynamics of the system.
                gamma - The discount factor of the system.
                regularization_lambda - The regularization parameter of the policy.
                dynamics_model - The Koopman tensor of the system.
                state_minimums - The minimum values of the state. Should be a column vector.
                state_maximums - The maximum values of the state. Should be a column vector.
                all_actions - The actions that the policy can take. Should be a single dimensional array.
                cost - The cost function of the system. Function must take in states and actions and return scalars.
                save_data_path - The path to save the training data and policy model.
                dt - The time step of the system.
                learning_rate - The learning rate of the policy.
                w_hat_batch_size - The batch size of the policy.
                seed - Random seed for reproducibility.
                load_model - Boolean indicating whether or not to load a saved model.
                layer_1_dim - Dimension of first layer of policy neural network model.
                layer_2_dim - Dimension of second layer of policy neural network model.
        """

        self.seed = seed
        np.random.seed(self.seed)
        torch.manual_seed(self.seed)

        self.true_dynamics = true_dynamics
        self.gamma = gamma
        self.regularization_lambda = regularization_lambda
        self.dynamics_model = koopman_model
        self.phi = self.dynamics_model.phi
        self.psi = self.dynamics_model.psi
        self.state_minimums = state_minimums
        self.state_maximums = state_maximums
        self.all_actions = all_actions
        self.cost = cost
        self.save_data_path = save_data_path
        self.training_data_path = f"{self.save_data_path}/training_data"
        # self.value_function_weights_file_name = "value_function_weights.npy"
        self.value_function_weights_file_name = "value_function_weights.pt"
        self.dt = dt
        self.discount_factor = self.gamma**self.dt
        self.learning_rate = learning_rate
        self.w_hat_batch_size = w_hat_batch_size
        self.layer_1_dim = layer_1_dim
        self.layer_2_dim = layer_2_dim

        if load_model:
            self.policy_model = torch.load(f"{self.save_data_path}/policy.pt")
            # self.value_function_weights = np.load(f"{self.save_data_path}/{self.value_function_weights_file_name}")
            self.value_function_weights = torch.load(f"{self.save_data_path}/{self.value_function_weights_file_name}")
        else:
            # self.policy_model = nn.Sequential(
            #     nn.Linear(self.dynamics_model.x_dim, self.all_actions.shape[1]),
            #     nn.Softmax(dim=-1)
            # )
            self.policy_model = nn.Sequential(
                nn.Linear(self.dynamics_model.x_dim, self.layer_1_dim),
                nn.ReLU(),
                # nn.SiLU(),
                nn.Linear(self.layer_1_dim, self.layer_2_dim),
                nn.ReLU(),
                # nn.SiLU(),
                nn.Linear(self.layer_2_dim, self.all_actions.shape[1]),
                nn.Softmax(dim=-1)
            )

            # self.value_function_weights = np.zeros(self.dynamics_model.phi_column_dim)
            self.value_function_weights = torch.zeros(self.dynamics_model.phi_column_dim)
            # self.value_function_weights = torch.zeros(self.dynamics_model.phi_column_dim, requires_grad=True)

            def init_weights(m):
                if type(m) == torch.nn.Linear:
                    m.weight.data.fill_(0.0)

            self.policy_model.apply(init_weights)
            # self.value_function_weights.apply(init_weights)

        self.policy_model_optimizer = torch.optim.Adam(self.policy_model.parameters(), lr=self.learning_rate)
        # self.value_function_optimizer = torch.optim.Adam([self.value_function_weights], lr=self.learning_rate)

    def update_value_function_weights(self):
        """
            Update the weights for the value function in the dictionary space.
        """

        # Take state sample from dataset
        x_batch_indices = np.random.choice(
            self.dynamics_model.X.shape[1],
            self.w_hat_batch_size,
            replace=False
        )
        x_batch = self.dynamics_model.X[:, x_batch_indices] # (state_dim, w_hat_batch_size)
        phi_x_batch = self.dynamics_model.Phi_X[:, x_batch_indices] # (phi_dim, w_hat_batch_size)

        # Compute policy probabilities for each state in the batch
        with torch.no_grad():
            pi_response = self.policy_model(torch.Tensor(x_batch.T)).T.numpy() # (all_actions.shape[1], w_hat_batch_size)

        # Compute phi_x_prime for all states in the batch using all actions in the action space
        K_us = self.dynamics_model.K_(self.all_actions) # (all_actions.shape[1], phi_dim, phi_dim)
        phi_x_prime_batch = K_us @ phi_x_batch # (all_actions.shape[1], phi_dim, w_hat_batch_size)

        # Compute expected phi(x')
        phi_x_prime_batch_prob = np.einsum(
            'upw,uw->upw',
            phi_x_prime_batch,
            pi_response
        ) # (all_actions.shape[1], phi_dim, w_hat_batch_size)
        expectation_term_1 = phi_x_prime_batch_prob.sum(axis=0) # (phi_dim, w_hat_batch_size)

        # Compute expected reward
        rewards_batch = -self.cost(x_batch, self.all_actions) # (all_actions.shape[1], w_hat_batch_size)
        reward_batch_prob = np.einsum(
            'uw,uw->uw',
            rewards_batch,
            pi_response
        ) # (all_actions.shape[1], w_hat_batch_size)
        expectation_term_2 = np.array([
            reward_batch_prob.sum(axis=0) # (w_hat_batch_size,)
        ]) # (1, w_hat_batch_size)

        # Update value function weights
        self.value_function_weights = torch.linalg.lstsq(
            torch.Tensor((phi_x_batch - (self.discount_factor * expectation_term_1)).T),
            torch.Tensor(expectation_term_2.T)
        ).solution # (phi_dim, 1)

    def get_action(self, x, num_samples=1):
        """
            Estimate the policy distribution, sample actions, and compute the log probabilities of sampled actions.
            
            INPUTS:
                x - State column vector.
                
            OUTPUTS:
                The selected actions and log probabilities.
        """

        # Get action distribution from policy model
        action_probabilities = self.policy_model(torch.Tensor(x[:, 0]))

        # Get random index of action from distribution
        action_indices = np.random.choice(
            self.all_actions.shape[1],
            p=np.squeeze(action_probabilities.detach().numpy()),
            size=[num_samples]
        )

        # Select action and compute log probability for that action
        actions = self.all_actions[:, action_indices]
        log_probabilities = torch.log(action_probabilities[action_indices])

        return actions, log_probabilities

    def train(
        self,
        num_training_episodes,
        num_steps_per_episode,
        how_often_to_chkpt=250
    ):
        """
            Actor-Critic algorithm. Train the policy iteration model. This updates the class parameters without returning anything.
            After running this function, you can call `policy.get_action(x)` to get an action using the trained policy.

            INPUTS:
                num_training_episodes - Number of episodes for which to train.
                num_steps_per_episode - Number of steps per episode.
                how_often_to_chkpt - Number of training iterations to do before saving model weights and training data.
        """

        # epsilon = np.finfo(np.float32).eps.item()
        V_xs = []
        V_x_primes = []
        actions = []
        log_probs = []
        rewards = []

        # Random initial conditions for each episode
        initial_states = np.random.uniform(
            self.state_minimums,
            self.state_maximums,
            [self.dynamics_model.x_dim, num_training_episodes]
        ).T

        for episode_num in range(num_training_episodes):
            # Create arrays to save training data
            V_xs_per_episode = torch.zeros(num_steps_per_episode)
            V_x_primes_per_episode = torch.zeros_like(V_xs_per_episode)
            actions_per_episode = torch.zeros((num_steps_per_episode, self.all_actions.shape[1]))
            log_probs_per_episode = torch.zeros_like(V_xs_per_episode)
            rewards_per_episode = torch.zeros_like(V_xs_per_episode)

            # Extract initial state
            state = np.vstack(initial_states[episode_num])

            for step_num in range(num_steps_per_episode):
                # Compute V_x
                # V_x = torch.Tensor(self.value_function_weights.T @ self.phi(state))
                # V_x = self.value_function_weights.T @ self.phi(state)
                V_x = self.value_function_weights.T @ torch.Tensor(self.phi(state))
                # V_x = self.value_function_weights(torch.Tensor(state[:,0]))[0]
                V_xs_per_episode[step_num] = V_x[0, 0]

                # Get action and action probabilities for current state
                action, log_prob = self.get_action(state)
                actions_per_episode[step_num] = torch.Tensor(action[:, 0])
                log_probs_per_episode[step_num] = log_prob

                # Take action A, observe S', R
                next_state = self.true_dynamics(state, action)
                curr_reward = -self.cost(state, action)[0, 0]
                rewards_per_episode[step_num] = curr_reward

                # Compute V_x_prime
                # V_x_prime = self.value_function_weights.T @ self.dynamics_model.phi(next_state)
                V_x_prime = self.value_function_weights.T @ torch.Tensor(self.dynamics_model.phi(next_state))
                V_x_primes_per_episode[step_num] = V_x_prime[0, 0]

                # Update state for next loop
                state = next_state

            # Append data to arrays
            V_xs.append(V_xs_per_episode.detach().numpy())
            V_x_primes.append(V_x_primes_per_episode.detach().numpy())
            actions.append(actions_per_episode.detach().numpy())
            log_probs.append(log_probs_per_episode.detach().numpy())
            rewards.append(rewards_per_episode.detach().numpy())

            # Compute advantage
            target_V_xs_per_episode = rewards_per_episode + (self.discount_factor * V_x_primes_per_episode)
            advantage_per_episode = target_V_xs_per_episode - V_xs_per_episode

            # Compute actor and critic losses
            actor_loss = (-log_probs_per_episode * advantage_per_episode.detach()).mean()
            # actor_loss = (self.regularization_lambda * log_probs_per_episode - V_xs_per_episode).mean()
            # critic_loss = advantage.pow(2).mean()

            # Backpropagation
            self.policy_model_optimizer.zero_grad()
            # self.value_function_optimizer.zero_grad()
            actor_loss.backward()
            # critic_loss.backward()
            self.policy_model_optimizer.step()
            # self.value_function_optimizer.step()

            # Update value function weights
            self.update_value_function_weights()

            # Progress prints
            if episode_num == 0 or (episode_num+1) % how_often_to_chkpt == 0:
                total_discounted_reward = 0
                for i in range(num_steps_per_episode-1, -1, -1):
                    total_discounted_reward = rewards_per_episode[i] + (self.discount_factor*total_discounted_reward)
                print(f"Episode: {episode_num+1}, total reward: {rewards_per_episode.sum()} (discounted: {total_discounted_reward})")

                # Save models
                torch.save(self.policy_model, f"{self.save_data_path}/policy.pt")
                torch.save(self.value_function_weights, f"{self.save_data_path}/{self.value_function_weights_file_name}")

                # Save training data
                np.save(f"{self.training_data_path}/v_xs.npy", V_xs)
                np.save(f"{self.training_data_path}/v_x_primes.npy", V_x_primes)
                np.save(f"{self.training_data_path}/actions.npy", actions)
                np.save(f"{self.training_data_path}/log_probs.npy", log_probs)
                np.save(f"{self.training_data_path}/rewards.npy", rewards)